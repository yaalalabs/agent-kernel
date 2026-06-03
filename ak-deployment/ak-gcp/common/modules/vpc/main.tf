# VPC network
resource "google_compute_network" "main" {
  name                    = "${var.product_alias}-${var.env_alias}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
}

# Public subnet — for resources that need external access
resource "google_compute_subnetwork" "public" {
  name          = "${var.product_alias}-${var.env_alias}-public-subnet"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.main.id
  ip_cidr_range = var.public_subnet_cidr
}

# Private subnet — for Cloud Run, Functions, Redis, Firestore connectors
resource "google_compute_subnetwork" "private" {
  name                     = "${var.product_alias}-${var.env_alias}-private-subnet"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = var.private_subnet_cidr
  private_ip_google_access = true
}

# Cloud Router — required for Cloud NAT to work
resource "google_compute_router" "router" {
  name    = "${var.product_alias}-${var.env_alias}-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.main.id
}

# Cloud NAT — gives private subnet resources outbound internet access
resource "google_compute_router_nat" "nat" {
  name                               = "${var.product_alias}-${var.env_alias}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.router.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.private.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

# Firewall — allow internal traffic within the VPC
resource "google_compute_firewall" "allow_internal" {
  name    = "${var.product_alias}-${var.env_alias}-allow-internal"
  project = var.project_id
  network = google_compute_network.main.id

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "icmp"
  }

  source_ranges = [var.public_subnet_cidr, var.private_subnet_cidr]
}
