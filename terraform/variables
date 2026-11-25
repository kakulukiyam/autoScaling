variable "aws_region" {
  description = "Región de AWS donde se desplegará el Auto Scaling Group"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Nombre base del proyecto para nombrar los recursos"
  type        = string
  default     = "autoscaling-lab"
}

variable "environment" {
  description = "Entorno de despliegue"
  type        = string
  default     = "prod"
}

variable "instance_type" {
  description = "Tipo de instancia EC2 (capa gratuita)"
  type        = string
  default     = "t3.micro"
}

variable "min_size" {
  description = "Límite inferior de instancias en el Auto Scaling Group"
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Límite superior de instancias en el Auto Scaling Group"
  type        = number
  default     = 4
}

variable "desired_capacity" {
  description = "Capacidad inicial deseada"
  type        = number
  default     = 1
}
