# Azure region, try to use the same as your resource group to avoid cross-region issues and costs. Make sure the resources are available in the region you specify.
region = "centralus"
# The Azure Resource Group you want to deploy the resources into
resource_group_name = "openai_daily"
product_alias = "demo"
env_alias = "dev"
module_name = "api"
# Email integration for Azure APIM Put Your Own here
publisher_email="agentkernel@yaala.ai"