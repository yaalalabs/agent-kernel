
data "aws_iam_policy_document" "source-storage-policy-document" {

  statement {

    sid    = "AllowS3AccessLambda"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = [
      "s3:GetObject",
      "s3:ListBucket"
    ]

    resources = [
      aws_s3_bucket.source-storage.arn,
      "${aws_s3_bucket.source-storage.arn}/*"
    ]
  }

  statement {

    sid    = "DenyNonSSLRequests"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.source-storage.arn,
      "${aws_s3_bucket.source-storage.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

