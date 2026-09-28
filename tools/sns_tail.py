"""Subscribe a queue to the alert topic and print every alert AWS delivers.

This is the "proof" end of the AWS path: it reads alerts back out of SNS the
way a downstream consumer (pager, ticketing system) would, via an SQS queue
subscription. Works against moto locally or a real account::

    python tools/sns_tail.py                              # emulator on :5000
    python tools/sns_tail.py --endpoint ""                # real AWS
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import boto3

DEFAULT_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:5000")
QUEUE_NAME = "claimswatch-sns-tail"


def client_kwargs(endpoint: str, region: str) -> dict[str, Any]:
    """boto3 client arguments; placeholder credentials suffice for an emulator."""
    kwargs: dict[str, Any] = {"region_name": region}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs.setdefault("aws_access_key_id", os.environ.get("AWS_ACCESS_KEY_ID", "testing"))
        kwargs.setdefault(
            "aws_secret_access_key", os.environ.get("AWS_SECRET_ACCESS_KEY", "testing")
        )
    return kwargs


def subscribe(sns: Any, sqs: Any, topic_name: str) -> str:
    """Create (or reuse) the topic and a queue subscribed to it; return the queue URL."""
    topic_arn = sns.create_topic(Name=topic_name)["TopicArn"]
    queue_url = sqs.create_queue(QueueName=QUEUE_NAME)["QueueUrl"]
    attributes = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
    queue_arn = attributes["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)
    print(f"listening on {topic_arn} via {queue_arn}", flush=True)
    return str(queue_url)


def print_message(body: str) -> None:
    """Print the SNS envelope's id and subject, then the alert JSON."""
    envelope = json.loads(body)
    print(f"\nSNS MessageId {envelope['MessageId']}\nSubject: {envelope.get('Subject')}")
    print(json.dumps(json.loads(envelope["Message"]), indent=2), flush=True)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Print alerts delivered through SNS.")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help='"" for real AWS')
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--topic", default=os.environ.get("SNS_TOPIC_NAME", "claimswatch-alerts"))
    parser.add_argument("--once", action="store_true", help="exit after the first message")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    kwargs = client_kwargs(args.endpoint, args.region)
    sqs = boto3.client("sqs", **kwargs)
    queue_url = subscribe(boto3.client("sns", **kwargs), sqs, args.topic)
    try:
        while True:
            response = sqs.receive_message(
                QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=5
            )
            for message in response.get("Messages", []):
                print_message(message["Body"])
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                if args.once:
                    return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
