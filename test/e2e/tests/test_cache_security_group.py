# Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may
# not use this file except in compliance with the License. A copy of the
# License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

"""Integration tests for the Elasticache CacheSecurityGroup resource
"""

import pytest
import boto3
import logging
import time

from acktest.resources import random_suffix_name
from acktest.k8s import resource as k8s
from acktest import tags as tagutil
from e2e import service_marker, CRD_GROUP, CRD_VERSION, load_elasticache_resource
from e2e.replacement_values import REPLACEMENT_VALUES

RESOURCE_PLURAL = "cachesecuritygroups"
UPDATE_WAIT_SECS = 30


@pytest.fixture(scope="module")
def elasticache_client():
    return boto3.client('elasticache')


@pytest.fixture
def simple_cache_security_group(elasticache_client):
    """Fixture to create a simple cache security group for testing"""
    group_name = random_suffix_name("ack-test-csg", 32)

    replacements = REPLACEMENT_VALUES.copy()
    replacements["CACHE_SECURITY_GROUP_NAME"] = group_name
    replacements["DESCRIPTION"] = "ACK e2e test cache security group"

    resource_data = load_elasticache_resource(
        "cache_security_group",
        additional_replacements=replacements,
    )
    logging.debug(resource_data)

    ref = k8s.CustomResourceReference(
        CRD_GROUP, CRD_VERSION, RESOURCE_PLURAL,
        group_name, namespace="default",
    )
    _ = k8s.create_custom_resource(ref, resource_data)
    cr = k8s.wait_resource_consumed_by_controller(ref)

    assert cr is not None
    yield ref, cr

    # Teardown
    try:
        _ = k8s.delete_custom_resource(ref)
    except Exception:
        pass


@pytest.fixture
def cache_security_group_with_tags(elasticache_client):
    """Fixture to create a cache security group with tags for testing"""
    group_name = random_suffix_name("ack-test-csg-tags", 32)

    replacements = REPLACEMENT_VALUES.copy()
    replacements["CACHE_SECURITY_GROUP_NAME"] = group_name
    replacements["DESCRIPTION"] = "ACK e2e test cache security group with tags"

    resource_data = load_elasticache_resource(
        "cache_security_group_tags",
        additional_replacements=replacements,
    )
    logging.debug(resource_data)

    ref = k8s.CustomResourceReference(
        CRD_GROUP, CRD_VERSION, RESOURCE_PLURAL,
        group_name, namespace="default",
    )
    _ = k8s.create_custom_resource(ref, resource_data)
    cr = k8s.wait_resource_consumed_by_controller(ref)

    assert cr is not None
    yield ref, cr

    # Teardown
    try:
        _ = k8s.delete_custom_resource(ref)
    except Exception:
        pass


@service_marker
class TestCacheSecurityGroup:
    def test_create_delete_cache_security_group(self, simple_cache_security_group, elasticache_client):
        """Test basic creation and deletion of a cache security group"""
        (ref, cr) = simple_cache_security_group

        assert k8s.wait_on_condition(
            ref, "ACK.ResourceSynced", "True", wait_periods=10
        )

        # Verify the resource exists in AWS
        cr = k8s.get_resource(ref)
        assert cr is not None
        assert cr["spec"]["cacheSecurityGroupName"] is not None
        assert cr["spec"]["description"] == "ACK e2e test cache security group"

        # Verify via AWS API
        group_name = cr["spec"]["cacheSecurityGroupName"]
        response = elasticache_client.describe_cache_security_groups(
            CacheSecurityGroupName=group_name
        )
        assert len(response["CacheSecurityGroups"]) == 1
        aws_group = response["CacheSecurityGroups"][0]
        assert aws_group["CacheSecurityGroupName"] == group_name
        assert aws_group["Description"] == "ACK e2e test cache security group"

        # Verify status fields
        assert cr["status"].get("ownerID") is not None

        # Delete and verify
        k8s.delete_custom_resource(ref)
        time.sleep(UPDATE_WAIT_SECS)

        # Verify the resource is deleted from AWS
        try:
            elasticache_client.describe_cache_security_groups(
                CacheSecurityGroupName=group_name
            )
            assert False, "Expected CacheSecurityGroupNotFoundFault"
        except elasticache_client.exceptions.CacheSecurityGroupNotFoundFault:
            pass

    def test_create_with_tags(self, cache_security_group_with_tags, elasticache_client):
        """Test creation of a cache security group with tags"""
        (ref, cr) = cache_security_group_with_tags

        assert k8s.wait_on_condition(
            ref, "ACK.ResourceSynced", "True", wait_periods=10
        )

        cr = k8s.get_resource(ref)
        assert cr is not None

        # Verify tags via AWS API
        group_arn = cr["status"]["ackResourceMetadata"]["arn"]
        tag_list = elasticache_client.list_tags_for_resource(ResourceName=group_arn)
        aws_tags = tagutil.clean(tag_list["TagList"])

        expected_tags = [
            {"Key": "Environment", "Value": "test"},
            {"Key": "Purpose", "Value": "e2e-testing"},
        ]
        assert len(aws_tags) == 2
        assert aws_tags == expected_tags

    def test_update_tags(self, simple_cache_security_group, elasticache_client):
        """Test updating tags on a cache security group"""
        (ref, cr) = simple_cache_security_group

        assert k8s.wait_on_condition(
            ref, "ACK.ResourceSynced", "True", wait_periods=10
        )

        # Add tags
        tag_updates = {
            "spec": {
                "tags": [
                    {"key": "Environment", "value": "staging"},
                    {"key": "Team", "value": "platform"},
                ]
            }
        }

        k8s.patch_custom_resource(ref, tag_updates)
        time.sleep(UPDATE_WAIT_SECS)

        # Wait for sync after tag update
        assert k8s.wait_on_condition(
            ref, "ACK.ResourceSynced", "True", wait_periods=10
        )

        # Verify tags via AWS API
        cr = k8s.get_resource(ref)
        group_arn = cr["status"]["ackResourceMetadata"]["arn"]
        tag_list = elasticache_client.list_tags_for_resource(ResourceName=group_arn)
        aws_tags = tagutil.clean(tag_list["TagList"])

        expected_tags = [
            {"Key": "Environment", "Value": "staging"},
            {"Key": "Team", "Value": "platform"},
        ]
        assert len(aws_tags) == 2
        assert aws_tags == expected_tags
