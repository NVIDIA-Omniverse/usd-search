# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# standard modules
import asyncio
from dataclasses import dataclass
from typing import List, Optional, Union

# local / proprietary modules
from omni.auth.client import Auth, AuthStatus, Credentials, ProfileResponse, Profiles
from omni.client import Connection, StatusType
from omni.discovery import DiscoverySearch

# third party modules
from pydantic import AliasChoices, Field
from pydantic_settings.main import BaseSettings

from ...log_utils import prepare_message
from .. import StorageClientAuthenticationError
from ..data import DataClassGetter
from . import DEPLOYMENT_LOOKUP, logger
from .exceptions import NonAdminUser


class NucleusAuthEnv(BaseSettings):
    """Authentication configuration for Nucleus storage client.

    In case credential information is not explicitly initialized - this class would look for the following environment variables:
    * OV_USERNAME - username for the nucleus server
    * OV_PASSWORD - password for the nucleus server
    * OV_TOKEN - access token for the nucleus server
    * ASSERT_ADMIN_USER - trigger to verify admin access
    """

    assert_admin_user: bool = Field(default=True, description="trigger to verify admin access")
    user: Optional[str] = Field(
        default=None,
        description="User name",
        alias="ov_username",
        validation_alias=AliasChoices("ov_username", "user"),
    )
    password: Optional[str] = Field(
        default=None,
        description="User password",
        alias="ov_password",
        validation_alias=AliasChoices("ov_password", "password"),
    )
    token: Optional[str] = Field(default=None, description="Access token")


class NucleusAuth(NucleusAuthEnv):
    """Authentication configuration for Nucleus storage client.

    This class is a safe alternative to NucleusAuthEnv, as it expects credentials to be provided explicitly.
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (init_settings,)


@dataclass
class NucleusAuthResponse(DataClassGetter):
    auth: Auth = None
    auth_token: str = None


class NucleusStorageClientAuthenticationError(StorageClientAuthenticationError):
    pass


async def authenticate_connection(
    conn: Connection,
    token: str,
    timeout: Optional[float] = None,
) -> Auth:
    auth = await asyncio.wait_for(conn.authorize_token(token=token), timeout=timeout)
    if auth.status != StatusType.OK:
        raise NucleusStorageClientAuthenticationError(f"Auth failed: {auth.status}", reason=str(auth.status))

    return auth


async def auth_conn(
    conn,
    omni_server,
    auth: Union[NucleusAuthEnv, NucleusAuth],
    omni_connection_timeout,
) -> NucleusAuthResponse:
    """Authenticate connection."""
    if auth.token is not None:
        token = auth.token
    else:
        token = await get_admin_user_token(omni_server, auth=auth)

    if token:
        auth = await authenticate_connection(conn, token=token, timeout=omni_connection_timeout)
    else:
        auth: Auth = await asyncio.wait_for(
            conn.auth(username=auth.user, password=auth.password),
            omni_connection_timeout,
        )
    if auth.status != StatusType.OK:
        raise NucleusStorageClientAuthenticationError(f"auth failed: {auth.status}", reason=str(auth.status))

    return NucleusAuthResponse(auth=auth, auth_token=token)


async def get_profiles(
    token: str, ov_server: str, username: str, deployment: str = DEPLOYMENT_LOOKUP
) -> ProfileResponse:
    """Get profile information about the current user.

    Args:
        token (str): user access token
        ov_server (str): nucleus server
        username (str): username
        deployment (str, optional): Name of deployment lookup for discovery service. Defaults to `deployment_lookup`.

    Returns:
        ProfileResponse: Profile of the user
    """

    async with DiscoverySearch(ov_server) as search:
        async with await search.find(Profiles, meta={"deployment": deployment}) as profiles:
            results: List[ProfileResponse] = [p async for p in profiles.get_all(token) if p.username == username]

    if len(results) > 0:
        return results[0]
    else:
        return None


async def get_connection_token(
    omni_server: str,
    auth: Union[NucleusAuthEnv, NucleusAuth],
    deployment_lookup: str = DEPLOYMENT_LOOKUP,
) -> Optional[str]:
    token = None
    try:
        async with DiscoverySearch(omni_server) as search:
            async with await search.find(Credentials, meta={"deployment": deployment_lookup}) as credentials:
                auth_reply = await credentials.auth(auth.user, auth.password)
                logger.debug("auth status %s", auth_reply.status)
                if auth_reply.status == AuthStatus.OK:
                    token = auth_reply.access_token
                else:
                    raise NucleusStorageClientAuthenticationError(
                        f"Incorrect Authentication status: {auth_reply.status}"
                    )
    except asyncio.CancelledError as exc:
        raise asyncio.CancelledError(f"Authentication cancelled: {exc}")
    except Exception as exc:
        logger.exception("failed to use auth: %s", str(exc))
    return token


async def get_admin_user_token(
    omni_server,
    auth: Union[NucleusAuthEnv, NucleusAuth],
    deployment_lookup: str = DEPLOYMENT_LOOKUP,
) -> Optional[str]:
    # get connection token from nucleus
    token = await get_connection_token(omni_server, auth, deployment_lookup)
    if token is None:
        return token

    # get profile for the user
    profile = await get_profiles(token, omni_server, auth.user, deployment_lookup)

    if profile is None or not profile.profile.admin:
        prepare_message(
            msg="Running with a non-admin user account:",
            item_list=(
                [f"username: {profile.username}"] + [f"{k}: {v}" for k, v in profile.profile.items()]
                if profile is not None
                else []
            ),
            logger=logger.warning,
        )
        if auth.assert_admin_user:
            raise NonAdminUser(profile)

    return token
