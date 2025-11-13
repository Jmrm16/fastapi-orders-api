"""
Database seed script to quickly populate mock development data.
Usage:
    python scripts/seed_data.py
"""
import sys
import os

# Add root folder to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal, Base, engine
from app.models.user import User
from app.models.product import Product
from app.services.auth_service import get_password_hash


def seed():
    print("[*] Creating database tables if not present...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. Seed Admin
        admin = db.query(User).filter(User.email == "admin@novacommerce.io").first()
        if not admin:
            admin = User(
                email="admin@novacommerce.io",
                full_name="Admin Director",
                hashed_password=get_password_hash("AdminPass123!"),
                is_active=True,
                is_admin=True,
            )
            db.add(admin)
            print("[+] Seeded Admin user: admin@novacommerce.io / AdminPass123!")

        # 2. Seed Customer
        customer = db.query(User).filter(User.email == "customer@novacommerce.io").first()
        if not customer:
            customer = User(
                email="customer@novacommerce.io",
                full_name="John Doe",
                hashed_password=get_password_hash("CustomerPass123!"),
                is_active=True,
                is_admin=False,
            )
            db.add(customer)
            print("[+] Seeded Demo customer: customer@novacommerce.io / CustomerPass123!")

        # 3. Seed Products
        products_data = [
            {
                "sku": "PROD-LOGI-MX3S",
                "name": "Logitech MX Master 3S Wireless Mouse",
                "description": "Ergonomic quiet click mouse with 8K DPI sensor",
                "price": 99.99,
                "stock": 45,
            },
            {
                "sku": "PROD-KEYCHRON-Q1",
                "name": "Keychron Q1 Pro Custom Mechanical Keyboard",
                "description": "75% layout QMK/VIA wireless mechanical keyboard",
                "price": 199.99,
                "stock": 20,
            },
            {
                "sku": "PROD-DELL-U2723QE",
                "name": "Dell UltraSharp 27 4K USB-C Hub Monitor",
                "description": "IPS Black technology with 2000:1 contrast ratio",
                "price": 579.99,
                "stock": 12,
            },
            {
                "sku": "PROD-SONY-WH1000XM5",
                "name": "Sony WH-1000XM5 Noise Canceling Headphones",
                "description": "Industry-leading wireless noise-canceling headphones",
                "price": 349.99,
                "stock": 30,
            },
            {
                "sku": "PROD-CALDIGIT-TS4",
                "name": "CalDigit TS4 Thunderbolt 4 Dock",
                "description": "18 ports of extreme connectivity with 98W charging",
                "price": 399.99,
                "stock": 15,
            },
        ]

        for p_data in products_data:
            existing = db.query(Product).filter(Product.sku == p_data["sku"]).first()
            if not existing:
                p = Product(**p_data, is_active=True)
                db.add(p)
                print(f"[+] Seeded Product: {p_data['name']} (Stock: {p_data['stock']})")

        db.commit()
        print("\n[OK] Database seeded successfully!")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
