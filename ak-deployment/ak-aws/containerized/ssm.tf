# Placeholder SSM parameters for the secrets the application resolves through the aws_ssm secret
# provider (#858). Each is created once holding REPLACE_ME; set the real value out of band with
# `aws ssm put-parameter --overwrite` and Terraform leaves it alone from then on.
#
# ignore_changes keeps Terraform from writing the placeholder back over the real value, but the
# provider still reads the parameter on every refresh, so the real value is recorded in state.
resource "aws_ssm_parameter" "secret_placeholder" {
  for_each = toset(var.ssm_secret_keys)

  name        = "/ak/${var.prefix}/${lower(each.value)}"
  description = "${each.value} for ${var.prefix}. Created by Terraform as REPLACE_ME: overwrite it with the real value."
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}
