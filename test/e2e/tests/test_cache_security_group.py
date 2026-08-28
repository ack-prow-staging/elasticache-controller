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

"""Integration tests for the ElastiCache CacheSecurityGroup resource
"""

import pytest
import boto3
import logging
import time

from acktest.resources import random_suffix_name
from acktest.k8s import resource as k8s
from e2e import service_marker, CRD_GROUP, CRD_VERSION, load_elasticache_resource
from e2e.replacement_values import REPLACEMENT_VALUES

RESOURCE_PLURAL = "cachesecuritygroups"
UPDATE_WAIT_SECS = 30


@pytest.fixture(scope="module")
def elasticache_client():
    return boto3.client("elasticache")


@pytest.fixture
def simple_cache_security_group(elasticache_client):
    """Fixture to create a simple cache security group for testing"""
    group_name = random_suffix_name("ack-test-csg", 32)

    replacements = REPLACEMENT_VALUES.copy()
    replacements["CACHE_SECURITY_GROUP_NAME"] = group_name
    replacements["DESCRIPTION"] = "ACK test cache security group"

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
    assert k8s.wait_on_condition(ref, "ACK.ResourceSynced", "True", wait_periods=10)

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
    replacements["DESCRIPTION"] = "ACK test cache security group with tags"

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
    assert k8s.wait_on_condition(ref, "ACK.ResourceSynced", "True", wait_periods=10)

    yield ref, cr

    # Teardown
    try:
        _ = k8s.delete_custom_resource(ref)
    except Exception:
        pass


@service_marker
class TestCacheSecurityGroup:
    def test_create_delete(self, elasticache_client, simple_cache_security_group):
        """Test basic creation and deletion of a CacheSecurityGroup"""
        ref, cr = simple_cache_security_group

        # Verify the resource was created in AWS
        group_name = cr["spec"]["cacheSecurityGroupName"]
        aws_resp = elasticache_client.describe_cache_security_groups(
            CacheSecurityGroupName=group_name
        )
        assert len(aws_resp["CacheSecurityGroups"]) == 1
        aws_group = aws_resp["CacheSecurityGroups"][0]
        assert aws_group["CacheSecurityGroupName"] == group_name
        assert aws_group["Description"] == "ACK test cache security group"

        # Verify the CR status fields
        cr = k8s.get_resource(ref)
        assert cr["status"].get("ownerID") is not None
        assert cr["status"].get("ackResourceMetadata", {}).get("arn") is not None

        # Delete the resource
        _ = k8s.delete_custom_resource(ref)
        time.sleep(UPDATE_WAIT_SECS)

        # Verify the resource was deleted from AWS
        try:
            elasticache_client.describe_cache_security_groups(
                CacheSecurityGroupName=group_name
            )
            assert False, "Expected CacheSecurityGroupNotFoundFault"
        except elasticache_client.exceptions.CacheSecurityGroupNotFoundFault:
            pass

    def test_create_with_tags(self, elasticache_client, cache_security_group_with_tags):
        """Test creation of a CacheSecurityGroup with tags"""
        ref, cr = cache_security_group_with_tags

        group_name = cr["spec"]["cacheSecurityGroupName"]

        # Verify the resource was created in AWS
        aws_resp = elasticache_client.describe_cache_security_groups(
            CacheSecurityGroupName=group_name
        )
        assert len(aws_resp["CacheSecurityGroups"]) == 1

        # Verify tags via ListTagsForResource
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        tags_resp = elasticache_client.list_tags_for_resource(ResourceName=arn)
        tag_map = {t["Key"]: t["Value"] for t in tags_resp["TagList"]}
        assert tag_map.get("environment") == "testing"
        assert tag_map.get("managed-by") == "ack"

    def test_update_tags(self, elasticache_client, cache_security_group_with_tags):
        """Test updating tags on a CacheSecurityGroup"""
        ref, cr = cache_security_group_with_tags

        # Update tags
        updates = {
            "spec": {
                "tags": [
                    {"key": "environment", "value": "production"},
                    {"key": "new-tag", "value": "new-value"},
                ]
            }
        }
        k8s.patch_custom_resource(ref, updates)
        time.sleep(UPDATE_WAIT_SECS)

        # Wait for sync
        assert k8s.wait_on_condition(ref, "ACK.ResourceSynced", "True", wait_periods=10)

        # Verify tags were updated in AWS
        cr = k8s.get_resource(ref)
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        tags_resp = elasticache_client.list_tags_for_resource(ResourceName=arn)
        tag_map = {t["Key"]: t["Value"] for t in tags_resp["TagList"]}
        assert tag_map.get("environment") == "production"
        assert tag_map.get("new-tag") == "new-value"
        assert "managed-by" not in tag_map
