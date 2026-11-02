#!/bin/bash
# Scale the e2e messaging ECS service(s) up for a test run, or down to 0 tasks between runs.
#
# The deployment idles at 0 tasks so Fargate isn't billed all week for a weekly test. The API
# Gateway, ALB and webhook registrations stay in place, so webhook URLs don't change.
#
# Usage: ./scale.sh up     # 1 task; waits until the service is stable
#        ./scale.sh down   # 0 tasks
#
# Reads region and prefix (the cluster name) from terraform.tfvars, like deploy.sh.
set -euo pipefail

cd "$(dirname "$0")"

function read_tfvar() {
	awk -F'=' -v k="$1" '$1 ~ "^[[:space:]]*"k"[[:space:]]*$" {gsub(/[" ]/, "", $2); print $2; exit}' terraform.tfvars
}

case "${1-}" in
up) count=1 ;;
down) count=0 ;;
*)
	echo "Usage: $0 up|down" >&2
	exit 2
	;;
esac

region=$(read_tfvar region)
cluster=$(read_tfvar prefix)

services=$(aws ecs list-services --cluster "$cluster" --region "$region" --query 'serviceArns' --output text)
if [[ -z "$services" || "$services" == "None" ]]; then
	# Nothing is running, so `down` has nothing to do (e.g. CI cleanup after a failed first provisioning).
	if [[ "$count" -eq 0 ]]; then
		echo "No ECS service in cluster '${cluster}' (region ${region}); nothing to scale down"
		exit 0
	fi
	echo "Could not find any ECS service in cluster '${cluster}' (region ${region}) — provision it first" >&2
	exit 1
fi

for arn in $services; do
	name="${arn##*/}"
	resource_id="service/${cluster}/${name}"
	
	has_target=$(aws application-autoscaling describe-scalable-targets --region "$region" \
		--service-namespace ecs --resource-ids "$resource_id" --query 'length(ScalableTargets)' --output text)
	if [[ "$has_target" != "0" ]]; then
		aws application-autoscaling register-scalable-target --region "$region" \
			--service-namespace ecs --scalable-dimension ecs:service:DesiredCount \
			--resource-id "$resource_id" --min-capacity "$count"
	fi

	aws ecs update-service --cluster "$cluster" --service "$name" --region "$region" \
		--desired-count "$count" --query 'service.serviceName' --output text >/dev/null
	echo "Set ${name} to ${count} task(s)"
done

if [[ "$count" -gt 0 ]]; then
	echo "Waiting for ECS services to become stable: ${services}"
	# Word-splitting on $services is intentional: one --services arg per ARN.
	aws ecs wait services-stable --cluster "$cluster" --services $services --region "$region"
	echo "ECS services are stable."
fi
