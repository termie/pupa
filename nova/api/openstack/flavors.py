# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import webob

from nova import db
from nova import exception
from nova.api.openstack import common
from nova.api.openstack import views


class Controller(common.OpenstackController):
    """Flavor controller for the OpenStack API."""

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "flavor": ["id", "name", "ram", "disk"],
                "link": ["rel", "type", "href"],
            }
        }
    }

    def index(self, req):
        """Return all flavors in brief."""
        items = self._get_flavors(req, is_detail=False)
        return dict(flavors=items)

    def detail(self, req):
        """Return all flavors in detail."""
        items = self._get_flavors(req, is_detail=True)
        return dict(flavors=items)

    def _get_flavors(self, req, is_detail=True):
        """Helper function that returns a list of flavor dicts."""
        ctxt = req.environ['nova.context']
        flavors = db.api.instance_type_get_all(ctxt)
        builder = self._get_view_builder(req)
        items = [builder.build(flavor, is_detail=is_detail)
                 for flavor in flavors.values()]
        return items

    def show(self, req, id):
        """Return data about the given flavor id."""
        try:
            ctxt = req.environ['nova.context']
            flavor = db.api.instance_type_get_by_flavor_id(ctxt, id)
        except exception.NotFound:
            return webob.exc.HTTPNotFound()

        builder = self._get_view_builder(req)
        values = builder.build(flavor, is_detail=True)
        return dict(flavor=values)


class ControllerV10(Controller):
    def _get_view_builder(self, req):
        return views.flavors.ViewBuilder()


class ControllerV11(Controller):
    def _get_view_builder(self, req):
        base_url = req.application_url
        return views.flavors.ViewBuilderV11(base_url)

    def get_default_xmlns(self, req):
        return common.XML_NS_V11
