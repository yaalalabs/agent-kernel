# Dedicated deploy key (generated for this stack, no passphrase) rather than a
# personal/GitHub key, so the instance credential can be rotated on its own.
public_key_path = "~/.ssh/sarasavi_ec2.pub"

region        = "ap-south-1"
instance_type = "t4g.small"
