# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC
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

from sqlalchemy import *
from migrate import *

from nova import log as logging


meta = MetaData()


networks = Table('networks', meta,
        Column('id', Integer(),  primary_key=True, nullable=False),
        )


#
# New Tables
#


#
# Tables to alter
#

networks_label = Column(
        'label',
        String(length=255, convert_unicode=False, assert_unicode=None,
               unicode_error=None, _warn_on_bytestring=False))


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    networks.create_column(networks_label)
