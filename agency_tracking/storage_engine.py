# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Cloudflare R2 (S3-compatible object storage), for the documents that don't belong in
# Frappe's own local file storage: Finance receipt images, generated Injaz papers, generated
# CV PDFs, parsed contracts/visas, applicant photos. One upload function, reused everywhere.
# Key convention:
#   agency/{applicant_name}/{category}/{filename}
# where category is one of "cv", "injaz", "finance-receipts", "contracts", "visas", "photos".
#
# Credentials are left empty until an admin enters them in Storage Settings -- calls fail with a
# clear "not configured" error in the meantime, never crash the calling flow (same honesty
# standard as fetch_daily_fx_rates/push notifications elsewhere in this app). Once credentials
# and a bucket name are provided, the bucket itself is auto-provisioned on first use
# (ensure_bucket_exists): head_bucket to check, create_bucket if it 404s -- so an admin only has
# to create the R2 API token, not pre-create the bucket by hand.

import frappe

STORAGE_CATEGORIES = {"cv", "injaz", "finance-receipts", "contracts", "visas", "photos"}

# Per-process cache of buckets already verified/created this worker's lifetime, so head_bucket
# isn't re-issued on every single upload. Keyed by bucket name.
_verified_buckets = set()


def _r2_client():
	settings = frappe.get_single("Storage Settings")
	secret = settings.get_password("r2_secret_access_key", raise_exception=False)
	if not (settings.r2_account_id and settings.r2_access_key_id and secret and settings.r2_bucket_name):
		frappe.throw(
			"Cloudflare R2 is not configured yet (Storage Settings). "
			"An admin needs to enter the R2 credentials and bucket name.",
			frappe.ValidationError,
		)
	import boto3

	return (
		boto3.client(
			"s3",
			endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
			aws_access_key_id=settings.r2_access_key_id,
			aws_secret_access_key=secret,
		),
		settings,
	)


def ensure_bucket_exists(client, bucket_name):
	"""Verify the bucket is reachable; auto-create it if it doesn't exist yet.

	Contract (Phase 2): given valid credentials, an admin should not have to pre-create the
	bucket. We head_bucket first; a 404 / NoSuchBucket means "valid creds, bucket just isn't
	there yet" -> create_bucket. Any other ClientError (403 unauthorized, invalid access key,
	signature mismatch, endpoint unreachable) is surfaced as a clear frappe.ValidationError so
	the caller sees actionable feedback instead of an unhandled 500. Result is cached per
	process so the head_bucket round-trip happens once, not on every upload."""
	if bucket_name in _verified_buckets:
		return

	from botocore.exceptions import ClientError, BotoCoreError, EndpointConnectionError

	try:
		client.head_bucket(Bucket=bucket_name)
		_verified_buckets.add(bucket_name)
		return
	except ClientError as e:
		error_code = str(e.response.get("Error", {}).get("Code", ""))
		status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
		if error_code in ("404", "NoSuchBucket") or status == 404:
			# Valid creds, bucket absent -> provision it.
			try:
				client.create_bucket(Bucket=bucket_name)
				_verified_buckets.add(bucket_name)
				return
			except ClientError as ce:
				# A concurrent worker may have just created it -- treat "already owned by you" as success.
				ce_code = str(ce.response.get("Error", {}).get("Code", ""))
				if ce_code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
					_verified_buckets.add(bucket_name)
					return
				frappe.throw(
					f"R2 bucket '{bucket_name}' does not exist and could not be created ({ce_code or ce}). "
					"Check that the API token has bucket-create permission.",
					frappe.ValidationError,
				)
		elif error_code in ("403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
			frappe.throw(
				f"R2 rejected the credentials while accessing bucket '{bucket_name}' ({error_code}). "
				"Verify the Account ID, Access Key ID, and Secret Access Key in Storage Settings.",
				frappe.ValidationError,
			)
		else:
			frappe.throw(
				f"Could not verify R2 bucket '{bucket_name}': {error_code or e}.",
				frappe.ValidationError,
			)
	except (EndpointConnectionError, BotoCoreError) as e:
		frappe.throw(
			f"Could not reach Cloudflare R2 to verify bucket '{bucket_name}': {e}. "
			"Check the Account ID and network connectivity.",
			frappe.ValidationError,
		)


def build_object_key(applicant_name, category, filename):
	if category not in STORAGE_CATEGORIES:
		frappe.throw(
			f"Unknown storage category '{category}'. Expected one of: {', '.join(sorted(STORAGE_CATEGORIES))}.",
			frappe.ValidationError,
		)
	return f"agency/{applicant_name}/{category}/{filename}"


def upload_to_r2(file_content: bytes, key: str, content_type: str | None = None) -> str:
	"""Uploads raw bytes to the configured R2 bucket at `key`, returns the public URL. Ensures
	the bucket exists first (auto-creates on 404). Raises a clear ValidationError (not a crash)
	if Storage Settings isn't configured or the credentials/bucket can't be reached."""
	client, settings = _r2_client()
	ensure_bucket_exists(client, settings.r2_bucket_name)
	extra_args = {"ContentType": content_type} if content_type else {}
	client.put_object(Bucket=settings.r2_bucket_name, Key=key, Body=file_content, **extra_args)
	base = (settings.r2_public_url_base or "").rstrip("/")
	return f"{base}/{key}"


@frappe.whitelist()
def test_storage_connection():
	"""Admin setup helper: verifies Storage Settings credentials and that the bucket is ready
	(creating it if missing), then does a tiny round-trip write/delete to confirm object-level
	access. Returns a status dict rather than throwing, so a settings-page 'Test Connection'
	button can render success/failure cleanly. Never raises into the caller."""
	frappe.only_for(("System Manager", "Administrator"))
	try:
		client, settings = _r2_client()
	except frappe.ValidationError as e:
		return {"status": "not_configured", "message": str(e)}

	bucket = settings.r2_bucket_name
	try:
		ensure_bucket_exists(client, bucket)
	except frappe.ValidationError as e:
		return {"status": "error", "bucket": bucket, "message": str(e)}

	# Object-level round-trip: confirms put/delete work, not just bucket existence.
	probe_key = "agency/_connection_test/.probe"
	try:
		client.put_object(Bucket=bucket, Key=probe_key, Body=b"ok", ContentType="text/plain")
		client.delete_object(Bucket=bucket, Key=probe_key)
	except Exception as e:
		return {
			"status": "bucket_ready_write_failed",
			"bucket": bucket,
			"message": f"Bucket reachable but object write failed: {e}",
		}

	base = (settings.r2_public_url_base or "").rstrip("/")
	return {
		"status": "success",
		"bucket": bucket,
		"public_url_base": base,
		"message": f"Connected to R2 bucket '{bucket}' and verified read/write access.",
	}


def migrate_attach_to_r2(doc, fieldname, category, applicant_name=None):
	"""Shared receipt-upload path (2026-08-29) -- same behavior everywhere a receipt/photo is
	captured: Applicant Transaction.receipt_image, Injaz Attempt.receipt_photo,
	Clearance Step Payment.receipt_url. The field itself stays a normal Frappe Attach (so the
	browser gets Frappe's native upload widget, nothing custom to build) -- this just runs on
	save, notices the value is still a *local* Frappe file, uploads it to R2, repoints the
	field at the resulting public URL, and deletes the local copy so nothing is stored twice.

	Best-effort, like every other document-generation path in this app (contract parsing, FX
	fetch): if Storage Settings isn't configured yet, or anything else goes wrong, log it and
	leave the local file in place (still viewable via Frappe's own file serving) rather than
	blocking the save. Safe to call unconditionally on every save -- a value that's already an
	R2 URL (doesn't start with /files/ or /private/files/) is a no-op.
	"""
	value = doc.get(fieldname)
	if not value or not (value.startswith("/files/") or value.startswith("/private/files/")):
		return

	try:
		file_name = frappe.db.get_value("File", {"file_url": value}, "name")
		if not file_name:
			return
		file_doc = frappe.get_doc("File", file_name)
		content = file_doc.get_content()
		key = build_object_key(applicant_name or doc.name, category, file_doc.file_name)
		r2_url = upload_to_r2(content, key, content_type=file_doc.content_type)
		doc.set(fieldname, r2_url)
		frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
	except Exception:
		frappe.log_error(title="R2 receipt migration failed", message=f"{doc.doctype} {doc.name} {fieldname}")
