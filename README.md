# AWS Auto Scaling Lab (Nginx + ALB + t3.micro)

Proyecto de demostración de **Auto Scaling Group en AWS** desplegado mediante **Terraform** y **GitHub Actions con autenticación OIDC** (reutilizando el bootstrap multi-repositorio configurado en `agentes`).

## Arquitectura

- **Instancias EC2:** `t3.micro` (Capa Gratuita) con Amazon Linux 2023 y monitoreo detallado de 1 minuto.
- **Auto Scaling Group:**
  - Límite inferior (`min_size`): **1** instancia
  - Límite superior (`max_size`): **4** instancias
- **Application Load Balancer (ALB):** Balanceo Round-Robin sin sticky sessions hacia el puerto 80 de Nginx.
- **Alarmas CloudWatch (Step Scaling):**
  - **Scale-Up (`CPUUtilization >= 45%`, 1 min):** escala `+1` instancia entre 45–75% y `+3` instancias si `>= 75%` (alcanzando el límite superior de 4).
  - **Scale-Down (`CPUUtilization <= 25%`, 2 min):** escala `-1` instancia entre 10–25% y `-3` instancias si `< 10%` (regresando al límite inferior de 1).
- **Panel Web en Nginx (`/`)**:
  - Botón **Ejecutar Prueba de Estrés** (satura CPU en todas las instancias activas y nuevas del ASG).
  - Botón **Detener Estrés** (devuelve el CPU a reposo para activar la alarma de descenso).
  - **Prueba Visual de Balanceo de Carga** en tiempo real con barras por instancia y registro de peticiones.
  - Gráfica en vivo de `CPUUtilization`, estado de alarmas CloudWatch y actividades de Auto Scaling.

## CI/CD sin nuevo Bootstrap

Este repositorio **no** incluye carpeta `bootstrap/`. Reutiliza directamente:
- **Rol OIDC:** `arn:aws:iam::037668896847:role/citas-escolares-github-oidc-role`
- **Backend remoto Terraform:** bucket `citas-escolares-tfstate-btamu4` (`key = "autoscaling/prod/terraform.tfstate"`) y tabla DynamoDB `citas-escolares-tflocks`.
