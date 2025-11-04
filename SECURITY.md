# Security Policy

## Supported Versions

We release patches for security vulnerabilities in the following versions:

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| < Latest| :x:                |

We recommend always using the latest version of Agent Kernel to ensure you have the most up-to-date security patches.

## Reporting a Vulnerability

The Agent Kernel team takes security bugs seriously. We appreciate your efforts to responsibly disclose your findings and will make every effort to acknowledge your contributions.

### How to Report a Security Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report security vulnerabilities by:

1. **Email**: Send details to agentkernel@yaalalabs.com
   - Use a descriptive subject line (e.g., "Security: [Brief Description]")
   - Include detailed information about the vulnerability
   - Do not include exploit code unless specifically requested

2. **What to Include**:
   - Type of vulnerability
   - Full paths of source file(s) related to the vulnerability
   - Location of the affected source code (tag/branch/commit or direct URL)
   - Step-by-step instructions to reproduce the issue
   - Proof-of-concept or exploit code (if possible)
   - Impact of the vulnerability, including how an attacker might exploit it

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your vulnerability report within 48 hours
- **Updates**: We will provide regular updates on our progress (at minimum every 5 business days)
- **Timeline**: We aim to address critical vulnerabilities within 30 days
- **Disclosure**: We will work with you to understand and resolve the issue before any public disclosure
- **Credit**: We will credit you in the security advisory (unless you prefer to remain anonymous)

### Our Commitment

- We will not pursue legal action against security researchers who report vulnerabilities in good faith
- We will work with you to understand the scope and severity of the issue
- We will keep you informed of our progress towards fixing the vulnerability
- We will publicly acknowledge your responsible disclosure (if desired)

## Security Best Practices

When using Agent Kernel, please follow these security best practices:

### API Keys and Secrets

- **Never commit API keys or secrets** to version control
- Use environment variables or secure secret management systems
- Rotate credentials regularly
- Use least-privilege access principles

### Dependencies

- **Keep dependencies up to date**: Regularly update Agent Kernel and its dependencies
- Review security advisories for dependencies
- Use virtual environments to isolate projects

### Configuration

- **Validate input**: Always validate and sanitize user input
- **Limit permissions**: Run with minimum necessary permissions
- **Secure communication**: Use HTTPS/TLS for network communications
- **Authentication**: Implement proper authentication and authorization

### Cloud Deployments

- **Use IAM roles**: Leverage cloud provider IAM for permissions
- **Encrypt data**: Use encryption for data at rest and in transit
- **Network security**: Use VPCs, security groups, and network policies
- **Audit logging**: Enable comprehensive logging and monitoring

### Agent Safety

- **Sandbox execution**: Isolate agent execution environments when possible
- **Rate limiting**: Implement rate limiting to prevent abuse
- **Input validation**: Validate all inputs to agents and tools
- **Output filtering**: Review and filter agent outputs before use

## Security Updates

Security updates will be released as soon as possible after a vulnerability is confirmed. Updates will be announced through:

- GitHub Security Advisories
- Release notes
- Project documentation

## Scope

This security policy applies to:

- All code in the agent-kernel repository
- Official documentation and examples
- Deployment templates and configurations

It does not apply to:

- Third-party dependencies (report to their respective maintainers)
- Forked or modified versions not maintained by the core team
- Applications built using Agent Kernel (unless the vulnerability is in AgentKernel itself)

## Security Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [AWS Security Best Practices](https://aws.amazon.com/security/best-practices/)

## Questions

If you have questions about this security policy or Agent Kernel's security practices, please contact agentkernel@yaalalabs.com.

Thank you for helping keep Agent Kernel and our users safe!
