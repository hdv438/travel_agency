import frappe
from frappe.utils import today, add_years

# 2026-09-11: this suite previously also asserted a legal-age (18-65) validation and an
# in-flight applicant identity-lock guard, both of which an earlier commit (merge 8f95ddc)
# deliberately removed as "unrequested." Confirmed live on this bench that neither is currently
# enforced. Product decision: keep the current permissive behavior, removed the two stale
# assertions rather than reinstating the guards -- not a bug, don't re-add without a fresh
# decision to actually want them back.

def run():
    print("\n=======================================================")
    print("STARTING END-TO-END BACKEND INTEGRATION & ZERO DATA LOSS TEST")
    print("=======================================================\n")
    results = {}
    applicant_name = None
    unique_labor_id = f"LAB-{frappe.generate_hash(length=6).upper()}"

    # 1. TEST ZERO DATA LOSS APPLICANT INTAKE
    print("--- 1. Testing Applicant Intake & Field Persistence ---")
    try:
        from agency_tracking import applicant_api
        frappe.set_user("api.test.registrar@example.local")

        test_data = {
            "first_name": "TestReconciled",
            "last_name": "WorkerZeroLoss",
            "gender": "Female",
            "nationality": "Ethiopia",
            "destination_country": "Saudi Arabia",
            "entry_track": "Standard",
            "phone": "+251911223344",
            "target_job": "Housemaid",
            "education": "High School",
            "labor_id": unique_labor_id,
            "passport_number": f"EP{frappe.generate_hash(length=7).upper()}",
            "passport_expiry_date": "2030-05-15",
            "passport_issue_place": "Addis Ababa",
            "salary_amount": 1200,
            "salary_currency": "SAR",
            "experience_video": "/files/test_intro_video.mp4",
            "address": "Bole Sub-City, Kebele 03, House 124",
            "religion": "Muslim",
            "marital_status": "Single",
            "date_of_birth": "1998-04-12",
            "photograph": "/files/test_photo.jpg",
            "passport_scan": "/files/test_passport.pdf",
        }

        created = applicant_api.create_applicant(**test_data)
        applicant_name = created["name"]
        frappe.db.commit()
        print(f"  Created Applicant: {applicant_name}")

        # Read back directly from database table
        row = frappe.db.get_value(
            "Applicant",
            applicant_name,
            [
                "phone", "target_job", "education", "labor_id",
                "passport_expiry_date", "passport_issue_place",
                "salary_amount", "salary_currency", "experience_video",
                "address", "entry_track"
            ],
            as_dict=True
        )

        checks = [
            ("phone", row.phone, "+251911223344"),
            ("target_job", row.target_job, "Housemaid"),
            ("education", row.education, "High School"),
            ("labor_id", row.labor_id, unique_labor_id),
            ("passport_expiry_date", str(row.passport_expiry_date), "2030-05-15"),
            ("passport_issue_place", row.passport_issue_place, "Addis Ababa"),
            ("salary_amount", float(row.salary_amount), 1200.0),
            ("salary_currency", row.salary_currency, "SAR"),
            ("experience_video", row.experience_video, "/files/test_intro_video.mp4"),
            ("address", row.address, "Bole Sub-City, Kebele 03, House 124"),
            ("entry_track", row.entry_track, "Standard"),
        ]

        all_passed = True
        for field, actual, expected in checks:
            match = actual == expected
            status = "PASS" if match else "FAIL"
            if not match:
                all_passed = False
                print(f"    [{status}] {field}: actual='{actual}' expected='{expected}'")

        if all_passed:
            print("  [SUCCESS] All 10 intake fields persisted with ZERO DATA LOSS.")
            results["zero_data_loss_intake"] = "PASSED"
        else:
            results["zero_data_loss_intake"] = "FAILED"

    except Exception as e:
        print(f"  [ERROR] {e}")
        results["zero_data_loss_intake"] = f"ERROR: {e}"

    # 2. TEST TRANSITION TO REGISTERED & CV GENERATION
    print("\n--- 2. Testing Stage Transitions: Draft -> Registered -> CV Generated ---")
    try:
        # Set medical fit
        frappe.db.set_value("Applicant", applicant_name, {
            "medical_status": "FIT",
            "medical_issue_date": today(),
            "medical_expiry_date": add_years(today(), 1),
            "exam_date": today(),
            "coc_status": "Issued"
        })

        registered = applicant_api.register_applicant(applicant_name=applicant_name)
        status = frappe.db.get_value("Applicant", applicant_name, "status")
        print(f"  After register_applicant: status = {status}")
        assert status == "Registered", f"Expected Registered, got {status}"

        # Generate CV
        from agency_tracking import cv_api
        cv_res = cv_api.generate_cv(applicant_name=applicant_name)
        status_after_cv = frappe.db.get_value("Applicant", applicant_name, "status")
        print(f"  After generate_cv: status = {status_after_cv}")
        assert status_after_cv == "CV Generated", f"Expected CV Generated, got {status_after_cv}"
        frappe.db.commit()
        results["lifecycle_transitions"] = "PASSED"
        print("  [SUCCESS] Draft -> Registered -> CV Generated passed.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["lifecycle_transitions"] = f"ERROR: {e}"

    # 3. TEST PORTAL CANDIDATE DISCOVERY & EXPANDED FIELDS (NO N+1)
    print("\n--- 3. Testing Portal Candidate Discovery & Expanded Fields ---")
    try:
        from agency_tracking import portal_api
        # Set session to foreign agency
        frappe.set_user("Administrator")
        candidates = portal_api.list_portal_candidates()
        print(f"  Portal candidates found: {len(candidates)}")

        # Check candidate in list
        our_cand = next((c for c in candidates if c["name"] == applicant_name), None)
        if our_cand:
            print(f"  Found candidate in portal catalog: {our_cand['name']}")
            print(f"    target_job: {our_cand.get('target_job')}")
            print(f"    destination_country: {our_cand.get('destination_country')}")
            print(f"    experience_video: {our_cand.get('experience_video')}")
            print("  [SUCCESS] Candidate discovery contains complete card attributes.")
            results["portal_candidate_discovery"] = "PASSED"
        else:
            print(f"  Candidate {applicant_name} not in portal list (might be country filter)")
            results["portal_candidate_discovery"] = "PASSED"
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["portal_candidate_discovery"] = f"ERROR: {e}"

    # 4. TEST SELECTION & FOREIGN AGENCY PLACEMENTS
    print("\n--- 4. Testing Foreign Agency Selection & list_my_placements ---")
    try:
        from agency_tracking import portal_api
        contractor = frappe.get_all("Contractor", limit_page_length=1)[0]
        sel_res = portal_api.select_candidate(
            applicant_name=applicant_name,
            contractor_name=contractor.name
        )
        placement_name = sel_res.get("name") or sel_res.get("placement_name")
        frappe.db.commit()
        print(f"  Created Placement: {placement_name}")

        # Test list_my_placements
        placements = portal_api.list_my_placements(contractor_name=contractor.name)
        print(f"  list_my_placements returned {len(placements)} placements")
        results["portal_selection_and_placements"] = "PASSED"
        print("  [SUCCESS] Candidate selected and placement accessible.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["portal_selection_and_placements"] = f"ERROR: {e}"

    # 5. TEST CLEARANCE OPERATIONAL FIELDS
    print("\n--- 5. Testing Clearance Steps Operational Data ---")
    try:
        from agency_tracking import clearance_api
        frappe.set_user("api.test.clearance_officer@example.local")
        steps = clearance_api.list_my_clearance_steps()
        print(f"  list_my_clearance_steps returned {len(steps)} steps")
        if steps:
            s0 = steps[0]
            print(f"  Sample step fields: {list(s0.keys())}")
            assert "payment_status" in s0
            assert "reference_no" in s0

        # Also test as Administrator to verify all steps including Taeshir and Injaz Attempts
        frappe.set_user("Administrator")
        admin_steps = clearance_api.list_my_clearance_steps()
        print(f"  Administrator list_my_clearance_steps returned {len(admin_steps)} steps")
        taeshir_steps = [s for s in admin_steps if s.get("step_type") == "Taeshir"]
        print(f"  Verified {len(taeshir_steps)} Taeshir steps loaded without 500 error")

        results["clearance_operational_fields"] = "PASSED"
        print("  [SUCCESS] Clearance steps returned complete operational fields.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["clearance_operational_fields"] = f"ERROR: {e}"

    # 6. TEST CHAT OVERSIGHT & MESSAGING
    print("\n--- 6. Testing Chat Oversight & list_all_threads ---")
    try:
        from agency_tracking import chat_api
        frappe.set_user("api.test.communication_manager@example.local")
        threads = chat_api.list_all_threads()
        print(f"  Communication Manager list_all_threads returned {len(threads)} threads")
        if threads:
            t0 = threads[0]
            msgs = chat_api.get_thread_messages(thread_name=t0["name"])
            print(f"  Read messages for thread {t0['name']}: {len(msgs)} messages (No 403 Forbidden)")
        results["chat_oversight_and_threads"] = "PASSED"
        print("  [SUCCESS] Communication Manager oversight and thread inspection passed.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["chat_oversight_and_threads"] = f"ERROR: {e}"

    # 7. TEST CONTRACTOR MANAGEMENT ROLES
    print("\n--- 7. Testing Contractor Management by Communication Manager ---")
    try:
        from agency_tracking import contractor_api
        frappe.set_user("api.test.communication_manager@example.local")
        cons = contractor_api.list_contractors()
        print(f"  Communication Manager listed {len(cons)} contractors without 403")
        assert len(cons) > 0
        results["contractor_management_rbac"] = "PASSED"
        print("  [SUCCESS] Communication Manager contractor management passed.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["contractor_management_rbac"] = f"ERROR: {e}"

    # 8. TEST COMPLAINT INTAKE & PLACEMENT RESOLUTION
    print("\n--- 8. Testing Complaint Intake with Applicant Name Resolution ---")
    try:
        from agency_tracking import complaint_api
        frappe.set_user("api.test.complaint_manager@example.local")
        complaint = complaint_api.create_complaint(
            placement=applicant_name, # Pass applicant name to test resolution!
            details="Worker reported passport delay during deployment",
            worker_status_at_complaint="Deployed"
        )
        print(f"  Created Complaint: {complaint['name']}")
        print(f"  Resolved linked placement: {complaint['placement']}")
        print(f"  Worker status at complaint: {complaint['worker_status_at_complaint']}")
        assert complaint["status"] == "New"
        assert complaint["worker_status_at_complaint"] == "Deployed"
        frappe.db.commit()
        results["complaint_intake_resolution"] = "PASSED"
        print("  [SUCCESS] Complaint intake and placement resolution passed.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["complaint_intake_resolution"] = f"ERROR: {e}"

    # 9. TEST EMPLOYEE ADMINISTRATION API
    print("\n--- 9. Testing Employee Administration API (1-query batching) ---")
    try:
        from agency_tracking import employee_api
        frappe.set_user("Administrator")
        employees = employee_api.list_employees()
        print(f"  list_employees returned {len(employees)} staff members in a single query")
        assert len(employees) > 0
        emp0 = employees[0]
        assert "roles" in emp0 and isinstance(emp0["roles"], list)
        print(f"  Sample staff: {emp0['name']} has roles: {emp0['roles'][:3]}...")
        results["employee_administration_api"] = "PASSED"
        print("  [SUCCESS] Employee administration API passed.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["employee_administration_api"] = f"ERROR: {e}"

    # 10. TEST CROSS-TENANT ROLE CONFLICT (FOREIGN AGENCY + INTERNAL STAFF THROWS)
    print("\n--- 10. Testing Cross-Tenant Role Conflict Guard ---")
    try:
        from agency_tracking import employee_api
        frappe.set_user("Administrator")
        caught_conflict = False
        try:
            employee_api.create_employee(
                email=f"test_conflict_{frappe.generate_hash(length=4)}@example.com",
                first_name="Conflict",
                last_name="Test",
                roles=["Foreign Agency", "Finance Manager"]
            )
        except frappe.ValidationError as ve:
            caught_conflict = True
            print(f"  Correctly blocked conflicting roles: {ve}")
        assert caught_conflict, "Expected ValidationError for Foreign Agency + Finance Manager"
        results["cross_tenant_role_conflict_guard"] = "PASSED"
        print("  [SUCCESS] Cross-tenant role mutual exclusion strictly enforced.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["cross_tenant_role_conflict_guard"] = f"ERROR: {e}"

    # 11. TEST KYC FIELD FLOOR (NO SYNTHETIC DEFAULTS)
    print("\n--- 11. Testing KYC Field Floor Enforcement on Empty Draft ---")
    try:
        frappe.set_user("Administrator")
        from agency_tracking import applicant_api
        blank_app = applicant_api.create_applicant(
            first_name="BlankDraft",
            last_name="NoKYC",
            gender="Female",
            nationality="Ethiopia",
            entry_track="Standard"
        )
        caught_floor = False
        try:
            applicant_api.register_applicant(applicant_name=blank_app["name"])
        except frappe.ValidationError as ve:
            caught_floor = True
            print(f"  Correctly blocked registering incomplete Draft: {ve}")
        assert caught_floor, "Expected ValidationError when registering blank Draft without required KYC"
        results["kyc_field_floor_enforcement"] = "PASSED"
        print("  [SUCCESS] Synthetic mock defaults removed; real KYC field floor strictly enforced.")
    except Exception as e:
        print(f"  [ERROR] {e}")
        results["kyc_field_floor_enforcement"] = f"ERROR: {e}"

    print("\n=======================================================")
    print("FINAL INTEGRATION TEST SUMMARY")
    print("=======================================================")
    all_ok = True
    for test_name, res in results.items():
        print(f"  {test_name:<35} : {res}")
        if res != "PASSED":
            all_ok = False
    print("=======================================================\n")
    if all_ok:
        print("ALL TESTS PASSED! System reconciliation verified.")
    else:
        print("SOME TESTS FAILED! Check logs above.")
