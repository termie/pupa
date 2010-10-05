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
Root WSGI middleware for all API controllers.
"""

import routes
import webob.dec

from nova import flags
from nova import wsgi
from nova.api import cloudpipe
from nova.api import ec2
from nova.api import rackspace
from nova.api.ec2 import metadatarequesthandler


flags.DEFINE_string('rsapi_subdomain', 'rs', 
                    'subdomain running the RS API')
flags.DEFINE_string('ec2api_subdomain', 'ec2', 
                    'subdomain running the EC2 API')
flags.DEFINE_string('FAKE_subdomain', None, 
                    'set to rs or ec2 to fake the subdomain of the host for testing')
FLAGS = flags.FLAGS


class API(wsgi.Router):
    """Routes top-level requests to the appropriate controller."""

    def __init__(self):
        rsdomain =  {'sub_domain': [FLAGS.rsapi_subdomain]}
        ec2domain = {'sub_domain': [FLAGS.ec2api_subdomain]}
        # If someone wants to pretend they're hitting the RS subdomain
        # on their local box, they can set FAKE_subdomain to 'rs', which
        # removes subdomain restrictions from the RS routes below.
        if FLAGS.FAKE_subdomain == 'rs':
            rsdomain = {}
        elif FLAGS.FAKE_subdomain == 'ec2':
            ec2domain = {}
        mapper = routes.Mapper()
        mapper.sub_domains = True
        mapper.connect("/", controller=self.rsapi_versions, 
                            conditions=rsdomain)
        mapper.connect("/v1.0/{path_info:.*}", controller=rackspace.API(),
                            conditions=rsdomain)

        mapper.connect("/", controller=self.ec2api_versions,
                            conditions=ec2domain)
        mapper.connect("/services/{path_info:.*}", controller=ec2.API(),
                            conditions=ec2domain)
        mapper.connect("/cloudpipe/{path_info:.*}", controller=cloudpipe.API())
        mrh = metadatarequesthandler.MetadataRequestHandler()
        for s in ['/latest',
                  '/2009-04-04',
                  '/2008-09-01',
                  '/2008-02-01',
                  '/2007-12-15',
                  '/2007-10-10',
                  '/2007-08-29',
                  '/2007-03-01',
                  '/2007-01-19',
                  '/1.0']:
            mapper.connect('%s/{path_info:.*}' % s, controller=mrh,
                           conditions=ec2domain)
        super(API, self).__init__(mapper)

    @webob.dec.wsgify
    def rsapi_versions(self, req):
        """Respond to a request for all OpenStack API versions."""
        response = {
                "versions": [
                    dict(status="CURRENT", id="v1.0")]}
        metadata = {
            "application/xml": {
                "attributes": dict(version=["status", "id"])}}
        return wsgi.Serializer(req.environ, metadata).to_content_type(response)

    @webob.dec.wsgify
    def ec2api_versions(self, req):
        """Respond to a request for all EC2 versions."""
        # available api versions
        versions = [
            '1.0',
            '2007-01-19',
            '2007-03-01',
            '2007-08-29',
            '2007-10-10',
            '2007-12-15',
            '2008-02-01',
            '2008-09-01',
            '2009-04-04',
        ]
        return ''.join('%s\n' % v for v in versions)

