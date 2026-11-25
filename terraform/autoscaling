locals {
  asg_name              = "${var.project_name}-asg-${var.environment}"
  scale_up_alarm_name   = "${var.project_name}-scale-up-${var.environment}"
  scale_down_alarm_name = "${var.project_name}-scale-down-${var.environment}"
}

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_launch_template" "web" {
  name_prefix   = "${var.project_name}-lt-"
  image_id      = data.aws_ssm_parameter.al2023_ami.value
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2.name
  }

  vpc_security_group_ids = [aws_security_group.ec2.id]

  # Monitoreo detallado (1 min) para que las alarmas reaccionen rápido al escalar arriba/abajo
  monitoring {
    enabled = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region            = var.aws_region
    app_bucket            = aws_s3_bucket.app_bundle.bucket
    app_key               = aws_s3_object.app_bundle.key
    app_bundle_etag       = data.archive_file.app_bundle.output_md5
    asg_name              = local.asg_name
    target_group_arn      = aws_lb_target_group.web.arn
    scale_up_alarm_name   = local.scale_up_alarm_name
    scale_down_alarm_name = local.scale_down_alarm_name
  }))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name        = "${var.project_name}-node-${var.environment}"
      Project     = var.project_name
      Environment = var.environment
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "web" {
  name                      = local.asg_name
  min_size                  = var.min_size
  max_size                  = var.max_size
  desired_capacity          = var.desired_capacity
  vpc_zone_identifier       = data.aws_subnets.supported.ids
  target_group_arns         = [aws_lb_target_group.web.arn]
  health_check_type         = "ELB"
  health_check_grace_period = 90
  default_cooldown          = 60

  enabled_metrics = [
    "GroupMinSize",
    "GroupMaxSize",
    "GroupDesiredCapacity",
    "GroupInServiceInstances",
    "GroupPendingInstances",
    "GroupTerminatingInstances",
    "GroupTotalInstances"
  ]

  launch_template {
    id      = aws_launch_template.web.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-node-${var.environment}"
    propagate_at_launch = true
  }

  lifecycle {
    ignore_changes = [desired_capacity]
  }
}

# ==============================================================================
# POLÍTICA Y ALARMA DE ESCALADO HACIA ARRIBA (Scale-Out: 1 -> 4)
# ==============================================================================
resource "aws_autoscaling_policy" "scale_up" {
  name                      = "${var.project_name}-scale-up-policy-${var.environment}"
  autoscaling_group_name    = aws_autoscaling_group.web.name
  policy_type               = "StepScaling"
  adjustment_type           = "ChangeInCapacity"
  estimated_instance_warmup = 60

  # CPU entre 45% y 75% -> +1 instancia
  step_adjustment {
    metric_interval_lower_bound = 0
    metric_interval_upper_bound = 30
    scaling_adjustment          = 1
  }

  # CPU >= 75% (estrés alto) -> +3 instancias (lleva de 1 al límite máximo de 4)
  step_adjustment {
    metric_interval_lower_bound = 30
    scaling_adjustment          = 3
  }
}

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = local.scale_up_alarm_name
  alarm_description   = "Escala hacia arriba cuando CPU promedio del ASG >= 45% durante 1 minuto"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Average"
  threshold           = 45
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.web.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_up.arn]
}

# ==============================================================================
# POLÍTICA Y ALARMA DE ESCALADO HACIA ABAJO (Scale-In: 4 -> 1)
# ==============================================================================
resource "aws_autoscaling_policy" "scale_down" {
  name                   = "${var.project_name}-scale-down-policy-${var.environment}"
  autoscaling_group_name = aws_autoscaling_group.web.name
  policy_type            = "StepScaling"
  adjustment_type        = "ChangeInCapacity"

  # CPU entre 10% y 25% -> -1 instancia
  step_adjustment {
    metric_interval_lower_bound = -15
    metric_interval_upper_bound = 0
    scaling_adjustment          = -1
  }

  # CPU < 10% (reposo completo) -> -3 instancias (regresa al límite mínimo de 1)
  step_adjustment {
    metric_interval_upper_bound = -15
    scaling_adjustment          = -3
  }
}

resource "aws_cloudwatch_metric_alarm" "low_cpu" {
  alarm_name          = local.scale_down_alarm_name
  alarm_description   = "Escala hacia abajo cuando CPU promedio del ASG <= 25% durante 2 minutos consecutivos"
  comparison_operator = "LessThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Average"
  threshold           = 25
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.web.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_down.arn]
}
