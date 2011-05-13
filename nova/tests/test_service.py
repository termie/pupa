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

"""
Unit Tests for remote procedure calls using queue
"""

import mox

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import rpc
from nova import test
from nova import service
from nova import manager

FLAGS = flags.FLAGS
flags.DEFINE_string("fake_manager", "nova.tests.test_service.FakeManager",
                    "Manager for testing")


class FakeManager(manager.Manager):
    """Fake manager for tests"""
    def test_method(self):
        return 'manager'


class ExtendedService(service.Service):
    def test_method(self):
        return 'service'


class ServiceManagerTestCase(test.TestCase):
    """Test cases for Services"""

    def test_message_gets_to_manager(self):
        serv = service.Service('test',
                               'test',
                               'test',
                               'nova.tests.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'manager')

    def test_override_manager_method(self):
        serv = ExtendedService('test',
                               'test',
                               'test',
                               'nova.tests.test_service.FakeManager')
        serv.start()
        self.assertEqual(serv.test_method(), 'service')


class ServiceTestCase(test.TestCase):
    """Test cases for Services"""

    def setUp(self):
        super(ServiceTestCase, self).setUp()
        self.mox.StubOutWithMock(service, 'db')

    def test_create(self):
        host = 'foo'
        binary = 'nova-fake'
        topic = 'fake'

        # NOTE(vish): Create was moved out of mox replay to make sure that
        #             the looping calls are created in StartService.
        app = service.Service.create(host=host, binary=binary)

        self.mox.StubOutWithMock(rpc,
                                 'TopicAdapterConsumer',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(rpc,
                                 'FanoutAdapterConsumer',
                                 use_mock_anything=True)
        rpc.TopicAdapterConsumer(connection=mox.IgnoreArg(),
                            topic=topic,
                            proxy=mox.IsA(service.Service)).AndReturn(
                                    rpc.TopicAdapterConsumer)

        rpc.TopicAdapterConsumer(connection=mox.IgnoreArg(),
                            topic='%s.%s' % (topic, host),
                            proxy=mox.IsA(service.Service)).AndReturn(
                                    rpc.TopicAdapterConsumer)

        rpc.FanoutAdapterConsumer(connection=mox.IgnoreArg(),
                            topic=topic,
                            proxy=mox.IsA(service.Service)).AndReturn(
                                    rpc.FanoutAdapterConsumer)

        rpc.TopicAdapterConsumer.attach_to_eventlet()
        rpc.TopicAdapterConsumer.attach_to_eventlet()
        rpc.FanoutAdapterConsumer.attach_to_eventlet()

        service_create = {'host': host,
                          'binary': binary,
                          'topic': topic,
                          'report_count': 0,
                          'availability_zone': 'nova'}
        service_ref = {'host': host,
                       'binary': binary,
                       'report_count': 0,
                       'id': 1}

        self.mox.ReplayAll()

        app.start()
        app.stop()
        self.assert_(app)
