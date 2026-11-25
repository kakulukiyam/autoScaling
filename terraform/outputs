output "alb_dns_name" {
  description = "DNS público del Application Load Balancer"
  value       = aws_lb.web.dns_name
}

output "app_url" {
  description = "URL pública del panel Nginx desplegado detrás del ALB"
  value       = "http://${aws_lb.web.dns_name}"
}

output "asg_name" {
  description = "Nombre del Auto Scaling Group"
  value       = aws_autoscaling_group.web.name
}

output "scale_up_alarm_name" {
  description = "Nombre de la alarma CloudWatch para escalado hacia arriba"
  value       = aws_cloudwatch_metric_alarm.high_cpu.alarm_name
}

output "scale_down_alarm_name" {
  description = "Nombre de la alarma CloudWatch para escalado hacia abajo"
  value       = aws_cloudwatch_metric_alarm.low_cpu.alarm_name
}

output "launch_template_id" {
  description = "ID del Launch Template"
  value       = aws_launch_template.web.id
}

output "launch_template_latest_version" {
  description = "Última versión del Launch Template"
  value       = aws_launch_template.web.latest_version
}

output "app_bucket_name" {
  description = "Bucket S3 donde se almacena el bundle de la aplicación"
  value       = aws_s3_bucket.app_bundle.bucket
}
