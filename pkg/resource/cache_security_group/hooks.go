// Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License"). You may
// not use this file except in compliance with the License. A copy of the
// License is located at
//
//     http://aws.amazon.com/apache2.0/
//
// or in the "license" file accompanying this file. This file is distributed
// on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
// express or implied. See the License for the specific language governing
// permissions and limitations under the License.

package cache_security_group

import (
	"context"

	svcapitypes "github.com/aws-controllers-k8s/elasticache-controller/apis/v1alpha1"
	"github.com/aws-controllers-k8s/elasticache-controller/pkg/util"
	ackcompare "github.com/aws-controllers-k8s/runtime/pkg/compare"
	ackrtlog "github.com/aws-controllers-k8s/runtime/pkg/runtime/log"
)

// customUpdateCacheSecurityGroup handles updates for cache security groups.
// Since there is no ModifyCacheSecurityGroup API, this method only handles
// tag updates via AddTagsToResource/RemoveTagsFromResource.
func (rm *resourceManager) customUpdateCacheSecurityGroup(
	ctx context.Context,
	desired *resource,
	latest *resource,
	delta *ackcompare.Delta,
) (updated *resource, err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.customUpdateCacheSecurityGroup")
	defer func() { exit(err) }()

	ko := desired.ko.DeepCopy()
	rm.setStatusDefaults(ko)

	// Handle tag updates
	if delta.DifferentAt("Spec.Tags") {
		if err := rm.syncTags(ctx, desired, latest); err != nil {
			return &resource{ko}, err
		}
	}

	return &resource{ko}, nil
}

// getTags retrieves the tags for a given CacheSecurityGroup
func (rm *resourceManager) getTags(
	ctx context.Context,
	resourceARN string,
) ([]*svcapitypes.Tag, error) {
	return util.GetTags(ctx, rm.sdkapi, rm.metrics, resourceARN)
}

// syncTags synchronizes the tags between the resource spec and the AWS resource
func (rm *resourceManager) syncTags(
	ctx context.Context,
	desired *resource,
	latest *resource,
) error {
	if latest.ko.Status.ACKResourceMetadata == nil || latest.ko.Status.ACKResourceMetadata.ARN == nil {
		return nil
	}

	return util.SyncTags(
		ctx,
		desired.ko.Spec.Tags,
		latest.ko.Spec.Tags,
		latest.ko.Status.ACKResourceMetadata,
		convertToOrderedACKTags,
		rm.sdkapi,
		rm.metrics,
	)
}
