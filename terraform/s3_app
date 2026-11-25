resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Bucket S3 privado para almacenar el paquete de la aplicación Nginx + Agente Python
resource "aws_s3_bucket" "app_bundle" {
  bucket        = "${var.project_name}-app-${random_string.suffix.result}"
  force_destroy = true

  tags = {
    Name = "${var.project_name}-app-bundle"
  }
}

resource "aws_s3_bucket_public_access_block" "app_bundle" {
  bucket = aws_s3_bucket.app_bundle.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "archive_file" "app_bundle" {
  type        = "zip"
  source_dir  = "${path.module}/../app"
  output_path = "${path.module}/app_bundle.zip"
}

resource "aws_s3_object" "app_bundle" {
  bucket = aws_s3_bucket.app_bundle.id
  key    = "app.zip"
  source = data.archive_file.app_bundle.output_path
  etag   = data.archive_file.app_bundle.output_md5
}
