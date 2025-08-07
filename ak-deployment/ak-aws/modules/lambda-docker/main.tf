locals {
  source_path   = "${path.root}/${var.source_path}"
  path_include  = ["**"]
  path_exclude  = ["**/__pycache__/**"]
  files_include = setunion([for f in local.path_include : fileset(local.source_path, f)]...)
  files_exclude = setunion([for f in local.path_exclude : fileset(local.source_path, f)]...)
  files         = sort(setsubtract(local.files_include, local.files_exclude))

  dir_sha = sha1(join("", [for f in local.files : filesha1("${local.source_path}/${f}")]))
}

module "docker_build_from_ecr" {
  source = "terraform-aws-modules/lambda/aws//modules/docker-build"
  version = "7.20.0"

  create_ecr_repo = true
  ecr_repo        = "${var.product_alias}-${var.env_alias}-${var.module_name}"
  ecr_repo_lifecycle_policy = jsonencode({
    "rules" : [
      {
        "rulePriority" : 1,
        "description" : "Keep only the last 30 images",
        "selection" : {
          "tagStatus" : "any",
          "countType" : "imageCountMoreThan",
          "countNumber" : 30
        },
        "action" : {
          "type" : "expire"
        }
      }
    ]
  })

  use_image_tag        = false
  source_path          = local.source_path
  platform             = "linux/amd64"

  triggers = {
    dir_sha = local.dir_sha
  }
}
