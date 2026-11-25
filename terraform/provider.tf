terraform {
  required_version = ">= 1.5.0"

  # Reutiliza el backend remoto S3 y DynamoDB creado por el bootstrap de agentes (sin crear un bootstrap nuevo)
  backend "s3" {
    bucket         = "citas-escolares-tfstate-btamu4"
    key            = "autoscaling/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "citas-escolares-tflocks"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
