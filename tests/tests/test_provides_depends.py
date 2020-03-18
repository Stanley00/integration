#!/usr/bin/python
# Copyright 2020 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import subprocess
import time

from ..common_setup import enterprise_no_client
from .common_update import update_image, common_update_procedure
from .mendertesting import MenderTesting
from ..MenderAPI import auth, auth_v2, deploy, image, logger

from testutils.infra.device import MenderDevice


class TestProvidesDependsEnterprise(MenderTesting):
    def test_update_provides_depends(self, enterprise_no_client):
        """
        Perform two consecutive updates, the first adds virtual provides
        to the artifact and the second artifact depends on these provides.
        """

        DEMO_POLL_INTERVAL = 5
        IMAGE_NAME = "core-image-full-cmdline-qemux86-64.ext4"

        # Create tenant user
        auth.reset_auth_token()
        auth.new_tenant("admin", "bob@builder.org", "secret-service")
        token = auth.current_tenant["tenant_token"]

        # Create client setup with tenant token
        enterprise_no_client.new_tenant_docker_client("mender-client", token)
        mender_device = MenderDevice(enterprise_no_client.get_mender_clients()[0])
        mender_device.host_ip = enterprise_no_client.get_virtual_network_host_ip()

        # Wait for ssh to be open
        mender_device.ssh_is_opened()
        # Check that the device has authorized with the backend.
        device = auth_v2.get_devices(expected_devices=1)
        device_ids = [device[0]["id"]]
        auth_v2.accept_devices(1)
        assert len(auth_v2.get_devices_status("accepted")) == 1

        # Update client with and artifact with custom provides
        def prepare_provides_artifact(artifact_file, artifact_id):
            cmd = (
                # Package MenderAPI in the artifact, just a random folder.
                "directory-artifact-gen -o %s -n %s -t docker-client -d /tmp/test_file_update_module MenderAPI -- --provides foo:bar"
                % (artifact_file, artifact_id)
            )
            logger.info("Executing: " + cmd)
            subprocess.check_call(cmd, shell=True)
            return artifact_file

        deployment_id, _ = common_update_procedure(
            mender_device,
            mender_device.host_ip,
            make_artifact=prepare_provides_artifact,
            # We use verify_status=False, because update module updates are so
            # quick that it sometimes races past the 'inprogress' status without
            # the test framework having time to register it. That's not really
            # the part we're interested in though, so just skip it.
            verify_status=False,
        )
        deploy.check_expected_status("finished", deployment_id)

        # Issue another update which depends on the custom provides
        def prepare_depends_artifact(artifact_file, artifact_id):
            cmd = (
                # Package MenderAPI in the artifact, just a random folder.
                "directory-artifact-gen -o %s -n %s -t docker-client -d /tmp/test_file_update_module MenderAPI -- --depends foo:bar"
                % (artifact_file, artifact_id)
            )
            logger.info("Executing: " + cmd)
            subprocess.check_call(cmd, shell=True)
            return artifact_file

        deployment_id, _ = common_update_procedure(
            mender_device,
            mender_device.host_ip,
            make_artifact=prepare_depends_artifact,
            verify_status=False,
        )
        deploy.check_expected_status("finished", deployment_id)

        # Issue a third update with the same update as previous, this time
        # with insufficient provides -> no artifact status
        deployment_id, _ = common_update_procedure(
            make_artifact=prepare_depends_artifact, verify_status=False
        )

        # Retry for at most 60 seconds checking for deployment status update
        stat = None
        for i in range(60):
            time.sleep(1)
            stat = deploy.get_statistics(deployment_id)
            if stat.get("pending") == 0:
                break

        assert stat is not None
        assert stat.get("noartifact") == 1
