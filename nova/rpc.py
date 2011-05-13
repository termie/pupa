# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""AMQP-based RPC.

Queues have consumers and publishers.

No fan-out support yet.

"""

import json
import sys
import time
import traceback
import uuid

from carrot import connection as carrot_connection
from carrot import messaging
from eventlet import greenpool
from eventlet import greenthread

from nova import context
from nova import exception
from nova import fakerabbit
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger('nova.rpc')


FLAGS = flags.FLAGS
flags.DEFINE_integer('rpc_thread_pool_size', 1024, 'Size of RPC thread pool')
flags.DEFINE_boolean('fake_rabbit', False, 'use a fake rabbit')
flags.DEFINE_string('rabbit_host', 'localhost', 'rabbit host')
flags.DEFINE_integer('rabbit_port', 5672, 'rabbit port')
flags.DEFINE_string('rabbit_userid', 'guest', 'rabbit userid')
flags.DEFINE_string('rabbit_password', 'guest', 'rabbit password')
flags.DEFINE_string('rabbit_virtual_host', '/', 'rabbit virtual host')
flags.DEFINE_integer('rabbit_retry_interval', 10,
                     'rabbit connection retry interval')
flags.DEFINE_integer('rabbit_max_retries', 12, 'rabbit connection attempts')
flags.DEFINE_string('control_exchange', 'nova',
                    'the main exchange to connect to')


class Connection(carrot_connection.BrokerConnection):
    """Connection instance object."""

    @classmethod
    def instance(cls, new=True):
        """Returns the instance."""
        if new or not hasattr(cls, '_instance'):
            params = {}
            if FLAGS.fake_rabbit:
                params['backend_cls'] = fakerabbit.Backend
            else:
                params.update(dict(hostname=FLAGS.rabbit_host,
                                   port=FLAGS.rabbit_port,
                                   userid=FLAGS.rabbit_userid,
                                   password=FLAGS.rabbit_password,
                                   virtual_host=FLAGS.rabbit_virtual_host))


            # NOTE(vish): magic is fun!
            # pylint: disable=W0142
            if new:
                return cls(**params)
            else:
                cls._instance = cls(**params)
        return cls._instance

    @classmethod
    def recreate(cls):
        """Recreates the connection instance.

        This is necessary to recover from some network errors/disconnects.

        """
        try:
            del cls._instance
        except AttributeError, e:
            # The _instance stuff is for testing purposes. Usually we don't use
            # it. So don't freak out if it doesn't exist.
            pass
        return cls.instance()


class Consumer(messaging.Consumer):
    """Consumer base class.

    Contains methods for connecting the fetch method to async loops.

    """

    def __init__(self, *args, **kwargs):
        for i in xrange(FLAGS.rabbit_max_retries):
            if i > 0:
                time.sleep(FLAGS.rabbit_retry_interval)
            try:
                super(Consumer, self).__init__(*args, **kwargs)
                self.failed_connection = False
                break
            except Exception as e:  # Catching all because carrot sucks
                fl_host = FLAGS.rabbit_host
                fl_port = FLAGS.rabbit_port
                fl_intv = FLAGS.rabbit_retry_interval
                LOG.error(_('AMQP server on %(fl_host)s:%(fl_port)d is'
                            ' unreachable: %(e)s. Trying again in %(fl_intv)d'
                            ' seconds.') % locals())
                self.failed_connection = True
        if self.failed_connection:
            LOG.error(_('Unable to connect to AMQP server '
                        'after %d tries. Shutting down.'),
                      FLAGS.rabbit_max_retries)
            sys.exit(1)

    def fetch(self, no_ack=None, auto_ack=None, enable_callbacks=False):
        """Wraps the parent fetch with some logic for failed connection."""
        # TODO(vish): the logic for failed connections and logging should be
        #             refactored into some sort of connection manager object
        try:
            if self.failed_connection:
                # NOTE(vish): connection is defined in the parent class, we can
                #             recreate it as long as we create the backend too
                # pylint: disable=W0201
                self.connection = Connection.recreate()
                self.backend = self.connection.create_backend()
                self.declare()
            super(Consumer, self).fetch(no_ack, auto_ack, enable_callbacks)
            if self.failed_connection:
                LOG.error(_('Reconnected to queue'))
                self.failed_connection = False
        # NOTE(vish): This is catching all errors because we really don't
        #             want exceptions to be logged 10 times a second if some
        #             persistent failure occurs.
        except Exception, e:  # pylint: disable=W0703
            if not self.failed_connection:
                LOG.exception(_('Failed to fetch message from queue: %s' % e))
                self.failed_connection = True

    def attach_to_eventlet(self):
        """Only needed for unit tests!"""
        timer = utils.LoopingCall(self.fetch, enable_callbacks=True)
        timer.start(0.1)
        return timer


class AdapterConsumer(Consumer):
    """Calls methods on a proxy object based on method and args."""

    def __init__(self, connection=None, topic='broadcast', proxy=None):
        LOG.debug(_('Initing the Adapter Consumer for %s') % topic)
        self.proxy = proxy
        self.pool = greenpool.GreenPool(FLAGS.rpc_thread_pool_size)
        super(AdapterConsumer, self).__init__(connection=connection,
                                              topic=topic)

    def receive(self, *args, **kwargs):
        self.pool.spawn_n(self._receive, *args, **kwargs)

    @exception.wrap_exception
    def _receive(self, message_data, message):
        """Magically looks for a method on the proxy object and calls it.

        Message data should be a dictionary with two keys:
            method: string representing the method to call
            args: dictionary of arg: value

        Example: {'method': 'echo', 'args': {'value': 42}}

        """
        LOG.debug(_('received %s') % message_data)
        msg_id = message_data.pop('_msg_id', None)

        ctxt = _unpack_context(message_data)

        method = message_data.get('method')
        args = message_data.get('args', {})
        message.ack()
        if not method:
            # NOTE(vish): we may not want to ack here, but that means that bad
            #             messages stay in the queue indefinitely, so for now
            #             we just log the message and send an error string
            #             back to the caller
            LOG.warn(_('no method for message: %s') % message_data)
            msg_reply(msg_id, _('No method for message: %s') % message_data)
            return

        node_func = getattr(self.proxy, str(method))
        node_args = dict((str(k), v) for k, v in args.iteritems())
        # NOTE(vish): magic is fun!
        try:
            rval = node_func(context=ctxt, **node_args)
            if msg_id:
                msg_reply(msg_id, rval, None)
        except Exception as e:
            logging.exception('Exception during message handling')
            if msg_id:
                msg_reply(msg_id, None, sys.exc_info())
        return


class Publisher(messaging.Publisher):
    """Publisher base class."""
    pass


class TopicAdapterConsumer(AdapterConsumer):
    """Consumes messages on a specific topic."""

    exchange_type = 'topic'

    def __init__(self, connection=None, topic='broadcast', proxy=None):
        self.queue = topic
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        self.durable = False
        super(TopicAdapterConsumer, self).__init__(connection=connection,
                                    topic=topic, proxy=proxy)


class FanoutAdapterConsumer(AdapterConsumer):
    """Consumes messages from a fanout exchange."""

    exchange_type = 'fanout'

    def __init__(self, connection=None, topic='broadcast', proxy=None):
        self.exchange = '%s_fanout' % topic
        self.routing_key = topic
        unique = uuid.uuid4().hex
        self.queue = '%s_fanout_%s' % (topic, unique)
        self.durable = False
        LOG.info(_('Created "%(exchange)s" fanout exchange '
                   'with "%(key)s" routing key'),
                 dict(exchange=self.exchange, key=self.routing_key))
        super(FanoutAdapterConsumer, self).__init__(connection=connection,
                                    topic=topic, proxy=proxy)


class TopicPublisher(Publisher):
    """Publishes messages on a specific topic."""

    exchange_type = 'topic'

    def __init__(self, connection=None, topic='broadcast'):
        self.routing_key = topic
        self.exchange = FLAGS.control_exchange
        self.durable = False
        super(TopicPublisher, self).__init__(connection=connection)


class FanoutPublisher(Publisher):
    """Publishes messages to a fanout exchange."""

    exchange_type = 'fanout'

    def __init__(self, topic, connection=None):
        self.exchange = '%s_fanout' % topic
        self.queue = '%s_fanout' % topic
        self.durable = False
        LOG.info(_('Creating "%(exchange)s" fanout exchange'),
                 dict(exchange=self.exchange))
        super(FanoutPublisher, self).__init__(connection=connection)


class DirectConsumer(Consumer):
    """Consumes messages directly on a channel specified by msg_id."""

    exchange_type = 'direct'

    def __init__(self, connection=None, msg_id=None):
        self.queue = msg_id
        self.routing_key = msg_id
        self.exchange = msg_id
        self.auto_delete = True
        self.exclusive = True
        super(DirectConsumer, self).__init__(connection=connection)


class DirectPublisher(Publisher):
    """Publishes messages directly on a channel specified by msg_id."""

    exchange_type = 'direct'

    def __init__(self, connection=None, msg_id=None):
        self.routing_key = msg_id
        self.exchange = msg_id
        self.auto_delete = True
        super(DirectPublisher, self).__init__(connection=connection)


def msg_reply(msg_id, reply=None, failure=None):
    """Sends a reply or an error on the channel signified by msg_id.

    Failure should be a sys.exc_info() tuple.

    """
    if failure:
        message = str(failure[1])
        tb = traceback.format_exception(*failure)
        LOG.error(_("Returning exception %s to caller"), message)
        LOG.error(tb)
        failure = (failure[0].__name__, str(failure[1]), tb)
    conn = Connection.instance()
    publisher = DirectPublisher(connection=conn, msg_id=msg_id)
    try:
        publisher.send({'result': reply, 'failure': failure})
    except TypeError:
        publisher.send(
                {'result': dict((k, repr(v))
                                for k, v in reply.__dict__.iteritems()),
                 'failure': failure})
    publisher.close()


class RemoteError(exception.Error):
    """Signifies that a remote class has raised an exception.

    Containes a string representation of the type of the original exception,
    the value of the original exception, and the traceback.  These are
    sent to the parent as a joined string so printing the exception
    contains all of the relevent info.

    """

    def __init__(self, exc_type, value, traceback):
        self.exc_type = exc_type
        self.value = value
        self.traceback = traceback
        super(RemoteError, self).__init__('%s %s\n%s' % (exc_type,
                                                         value,
                                                         traceback))


def _unpack_context(msg):
    """Unpack context from msg."""
    context_dict = {}
    for key in list(msg.keys()):
        # NOTE(vish): Some versions of python don't like unicode keys
        #             in kwargs.
        key = str(key)
        if key.startswith('_context_'):
            value = msg.pop(key)
            context_dict[key[9:]] = value
    LOG.debug(_('unpacked context: %s'), context_dict)
    return context.RequestContext.from_dict(context_dict)


def _pack_context(msg, context):
    """Pack context into msg.

    Values for message keys need to be less than 255 chars, so we pull
    context out into a bunch of separate keys. If we want to support
    more arguments in rabbit messages, we may want to do the same
    for args at some point.

    """
    context = dict([('_context_%s' % key, value)
                   for (key, value) in context.to_dict().iteritems()])
    msg.update(context)


def call(context, topic, msg):
    """Sends a message on a topic and wait for a response."""
    LOG.debug(_('Making asynchronous call on %s ...'), topic)
    msg_id = uuid.uuid4().hex
    msg.update({'_msg_id': msg_id})
    LOG.debug(_('MSG_ID is %s') % (msg_id))
    _pack_context(msg, context)

    class WaitMessage(object):
        def __call__(self, data, message):
            """Acks message and sets result."""
            message.ack()
            if data['failure']:
                self.result = RemoteError(*data['failure'])
            else:
                self.result = data['result']

    wait_msg = WaitMessage()
    conn = Connection.instance()
    consumer = DirectConsumer(connection=conn, msg_id=msg_id)
    consumer.register_callback(wait_msg)

    conn = Connection.instance()
    publisher = TopicPublisher(connection=conn, topic=topic)
    publisher.send(msg)
    publisher.close()

    try:
        consumer.wait(limit=1)
    except StopIteration:
        pass
    consumer.close()
    # NOTE(termie): this is a little bit of a change from the original
    #               non-eventlet code where returning a Failure
    #               instance from a deferred call is very similar to
    #               raising an exception
    if isinstance(wait_msg.result, Exception):
        raise wait_msg.result
    return wait_msg.result


def cast(context, topic, msg):
    """Sends a message on a topic without waiting for a response."""
    LOG.debug(_('Making asynchronous cast on %s...'), topic)
    _pack_context(msg, context)
    conn = Connection.instance()
    publisher = TopicPublisher(connection=conn, topic=topic)
    publisher.send(msg)
    publisher.close()


def fanout_cast(context, topic, msg):
    """Sends a message on a fanout exchange without waiting for a response."""
    LOG.debug(_('Making asynchronous fanout cast...'))
    _pack_context(msg, context)
    conn = Connection.instance()
    publisher = FanoutPublisher(topic, connection=conn)
    publisher.send(msg)
    publisher.close()


def generic_response(message_data, message):
    """Logs a result and exits."""
    LOG.debug(_('response %s'), message_data)
    message.ack()
    sys.exit(0)


def send_message(topic, message, wait=True):
    """Sends a message for testing."""
    msg_id = uuid.uuid4().hex
    message.update({'_msg_id': msg_id})
    LOG.debug(_('topic is %s'), topic)
    LOG.debug(_('message %s'), message)

    if wait:
        consumer = messaging.Consumer(connection=Connection.instance(),
                                      queue=msg_id,
                                      exchange=msg_id,
                                      auto_delete=True,
                                      exchange_type='direct',
                                      routing_key=msg_id)
        consumer.register_callback(generic_response)

    publisher = messaging.Publisher(connection=Connection.instance(),
                                    exchange=FLAGS.control_exchange,
                                    durable=False,
                                    exchange_type='topic',
                                    routing_key=topic)
    publisher.send(message)
    publisher.close()

    if wait:
        consumer.wait()


if __name__ == '__main__':
    # You can send messages from the command line using
    # topic and a json string representing a dictionary
    # for the method
    send_message(sys.argv[1], json.loads(sys.argv[2]))
