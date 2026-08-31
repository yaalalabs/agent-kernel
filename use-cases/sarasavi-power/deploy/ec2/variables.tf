variable "region" {
  description = "AWS region (ap-south-1 = Mumbai, lowest latency to Sri Lanka)"
  type        = string
  default     = "ap-south-1"
}

variable "instance_type" {
  description = "t4g.small: 2 GB RAM (free-tier promo, arm64). t3.micro fits only 1 call."
  type        = string
  default     = "t4g.small"
}

variable "public_key_path" {
  description = "SSH public key used to push code and manage the instance"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  description = "CIDR allowed to SSH (tighten to your IP, e.g. 1.2.3.4/32)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "project" {
  type    = string
  default = "sarasavi-power"
}
