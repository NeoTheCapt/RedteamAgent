# Red Team Infrastructure Setup

## Terraform Automation
- Infrastructure as Code: define servers, DNS, firewalls in config files
- Architecture: 3 long-term servers (phishing, payload, C2) + 3 redirectors
- Redirectors are disposable; rebuild with `terraform apply` when burned
- Providers: DigitalOcean/AWS for VPS, CloudFlare for DNS
```hcl
# Example: create redirector droplet
resource "digitalocean_droplet" "c2-redirector" {
  image  = "ubuntu-18-04-x64"
  name   = "c2-redir"
  region = "nyc1"
  size   = "s-1vcpu-1gb"
}
```
- `terraform plan` -> `terraform apply` -> `terraform destroy`

## Phishing with GoPhish
- Web-based phishing framework
- Configure SMTP sending profile, email templates, landing pages
- Track opens, clicks, and credential submissions
- Host on separate server behind SMTP redirector

## Reverse Proxy Phishing (Modlishka)
```bash
apt install certbot
wget https://github.com/drk1wi/Modlishka/releases/download/v.1.1.0/Modlishka-linux-amd64
```
- Config: set `proxyDomain` (your domain) and `target` (victim site, e.g., gmail.com)
- MITM proxy: captures passwords AND 2FA tokens in real-time
- Requires DNS setup pointing your domain to Modlishka server

## SMTP Setup
- Configure PTR record for SMTP relay to reduce spam classification
- Use separate domain for phishing (protect primary C2 domain)
- SPF/DKIM/DMARC alignment for delivery success

## OpSec Considerations
- Separate infrastructure per function (phishing, C2, payload hosting)
- Use HTTPS with valid certificates (Let's Encrypt)
- Domain categorization/aging before engagement
- Rotate redirectors regularly; never expose team servers directly
