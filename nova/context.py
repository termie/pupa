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

"""RequestContext: context for requests that persist through all of nova."""

import datetime
import random

from nova import exception
from nova import utils


class RequestContext(object):
    """Security context and request information.

    Represents the user taking a given action within the system.

    """

    def __init__(self, tenant, user, groups=None, remote_address=None,
                 timestamp=None, request_id=None):
        self.user = user
        self.tenant = tenant
        self.groups = groups and groups or []
        self.remote_address = remote_address
        if not timestamp:
            timestamp = utils.utcnow()
        if isinstance(timestamp, str) or isinstance(timestamp, unicode):
            timestamp = utils.parse_isotime(timestamp)
        self.timestamp = timestamp
        if not request_id:
            chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890-'
            request_id = ''.join([random.choice(chars) for x in xrange(20)])
        self.request_id = request_id

    def to_dict(self):
        return {'user': self.user,
                'tenant': self.tenant,
                'groups': self.groups,
                'remote_address': self.remote_address,
                'timestamp': utils.isotime(self.timestamp),
                'request_id': self.request_id}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)
