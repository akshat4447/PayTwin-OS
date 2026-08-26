"""Reliability Lab — PayTwin native module.

Proves payment-integration correctness before production:
scenario engine + business-invariant engine + provider (Razorpay) pack +
webhook/chaos injection + release gate. Provider-independent core;
provider specifics live in packs and are traced to verified requirements.
"""
