## Description
<!-- Provide a brief description of the changes in this PR -->
This update resolves a DynamoDB creation issue where the table ARN was unknown at plan time, causing ECS IAM policy attachment to fail.

## Type of Change
<!-- Mark the relevant option with an "x" -->

- [x] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [x] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)
- [ ] Performance improvement
- [ ] Test update
- [ ] CI/CD update
- [ ] Other (please describe):


## Changes Made
<!-- List the main changes made in this PR -->

- change [( count = local.dynamodb_memory_table_arn != null ? 1 : 0 ) to ( count = var.create_dynamodb_memory_table == true ? 1 : 0 )]
- Corrected ECS task IAM policy attachment.
- Added missing create_tasks_iam_role variable.


## Checklist
<!-- Mark completed items with an "x" -->

- [x] My code follows the project's style guidelines
- [x] I have performed a self-review of my code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [x] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] Any dependent changes have been merged and published


