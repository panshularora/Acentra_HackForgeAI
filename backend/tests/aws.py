"""Read alerts back from moto the way a downstream consumer would."""

import json
from typing import Any

import boto3

REGION = "us-east-1"


def subscribe_queue(topic_arn: str) -> str:
    """Subscribe a new SQS queue to ``topic_arn`` and return the queue URL."""
    sqs = boto3.client("sqs", region_name=REGION)
    sns = boto3.client("sns", region_name=REGION)
    queue_url = sqs.create_queue(QueueName="oncall")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)
    return queue_url


def receive_envelopes(queue_url: str) -> list[dict[str, Any]]:
    """Every SNS envelope waiting in the queue, oldest first."""
    sqs = boto3.client("sqs", region_name=REGION)
    envelopes: list[dict[str, Any]] = []
    while messages := sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get(
        "Messages", []
    ):
        for message in messages:
            envelopes.append(json.loads(message["Body"]))
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
    return envelopes


def cloudwatch_messages(log_group: str, log_stream: str) -> list[str]:
    """The message of every event in a CloudWatch Logs stream, oldest first."""
    logs = boto3.client("logs", region_name=REGION)
    events = logs.get_log_events(logGroupName=log_group, logStreamName=log_stream)["events"]
    return [event["message"] for event in events]
