from nova import flags
from nova import log as logging
from nova import manager


FLAGS = flags.FLAGS
flags.DEFINE_string('echo_manager', 'nova.echo.manager.EchoManager',
                    'which manager to use for echo service')

LOG = logging.getLogger('nova.echo.manager')


class EchoManager(manager.Manager):
    def echo(self, context, value):
        """Simply returns whatever value is sent in"""
        LOG.debug(_("Received %s"), value)
        return value

    def context(self, context, value):
        """Returns dictionary version of context"""
        LOG.debug(_("Received %s"), context)
        return context.to_dict()

    def fail(self, context, value):
        """Raises an exception with the value sent in"""
        raise Exception(value)

