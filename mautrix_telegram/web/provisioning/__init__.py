# -*- coding: future_fstrings -*-
# mautrix-telegram - A Matrix-Telegram puppeting bridge
# Copyright (C) 2018 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from aiohttp import web
import logging
import json

from ...user import User
from ..common import AuthAPI


class ProvisioningAPI(AuthAPI):
    log = logging.getLogger("mau.web.provisioning")

    def __init__(self, config, loop):
        super().__init__(loop)
        self.secret = config["appservice.provisioning.shared_secret"]

        self.app = web.Application(loop=loop)

        self.app.router.add_route("GET", "/{mxid:@[^:]*:.+}/get_me", self.get_me)
        login_prefix = "/login/{mxid:@[^:]*:.+}"
        self.app.router.add_route("POST", f"{login_prefix}/bot_token", self.send_bot_token)
        self.app.router.add_route("POST", f"{login_prefix}/request_code", self.request_code)
        self.app.router.add_route("POST", f"{login_prefix}/send_code", self.send_code)
        self.app.router.add_route("POST", f"{login_prefix}/send_password", self.send_password)

    def get_login_response(self, status=200, state="", username="", mxid="", message="", error="",
                           errcode=""):
        if username:
            resp = {
                "state": "logged-in",
                "username": username,
            }
        elif message:
            resp = {
                "state": state,
                "message": message,
            }
        else:
            resp = {
                "state": state,
                "error": error,
                "errcode": errcode,
            }
        return web.json_response(resp, status=status)

    async def get_request_info(self, request: web.Request, get_data=True, fail_on_logged_in=True):
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {self.secret}":
            return None, None, self.get_login_response(error="Shared secret is not valid.",
                                                       errcode="shared_secret_invalid",
                                                       status=401)

        data = None
        if get_data:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                pass
            if not data:
                return None, None, self.get_login_response(error="Invalid JSON.",
                                                           errcode="json_invalid", status=400)

        mxid = request.match_info["mxid"]
        user = await User.get_by_mxid(mxid).ensure_started(even_if_no_session=True)
        if not user.puppet_whitelisted:
            return None, user, self.get_login_response(error="You are not whitelisted.",
                                                       errcode="mxid_not_whitelisted", status=403)
        elif fail_on_logged_in and await user.is_logged_in():
            return None, user, self.get_login_response(username=user.username, status=409)
        return data, user, None

    async def get_me(self, request: web.Request):
        data, user, err = await self.get_request_info(request, get_data=False,
                                                      fail_on_logged_in=False)
        if err is not None:
            return err
        if not await user.is_logged_in():
            return self.get_login_response(status=403, error="You are not logged in.",
                                           errcode="not_logged_in")
        me = await user.client.get_me()
        return web.json_response({
            "username": me.username,
            "first_name": me.first_name,
            "last_name": me.last_name,
            "phone": me.phone,
            "is_bot": me.bot,
        })

    async def send_bot_token(self, request: web.Request):
        data, user, err = await self.get_request_info(request)
        if err is not None:
            return err
        return await self.post_login_token(user, data.get("token", ""))

    async def request_code(self, request: web.Request):
        data, user, err = await self.get_request_info(request)
        if err is not None:
            return err
        return await self.post_login_phone(user, data.get("phone", ""))

    async def send_code(self, request: web.Request):
        data, user, err = await self.get_request_info(request)
        if err is not None:
            return err
        return await self.post_login_code(user, data.get("code", 0), password_in_data=False)

    async def send_password(self, request: web.Request):
        data, user, err = await self.get_request_info(request)
        if err is not None:
            return err
        return await self.post_login_password(user, data.get("password", ""))
