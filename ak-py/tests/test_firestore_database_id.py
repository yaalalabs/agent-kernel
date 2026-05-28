"""
Bug Condition Exploration Test for Firestore Database ID Configuration

**Validates: Requirements 2.1, 2.2, 2.4, 2.5, 2.6**

This test encodes the EXPECTED BEHAVIOR: when a named Firestore database is created
by Terraform and database_id is configured, the FirestoreDriver should successfully
connect to that named database and execute all operations without 404 errors.

CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
DO NOT attempt to fix the test or the code when it fails.

When this test passes after implementing the fix, it confirms the bug is resolved.
"""

import datetime
import os
import unittest
from unittest.mock import MagicMock, call, patch

import pytest


class TestFirestoreDatabaseIdBugCondition(unittest.TestCase):
    """
    Property 1: Bug Condition - Named Database Connection

    Test that when a named Firestore database is created by Terraform and database_id
    is configured, the FirestoreDriver successfully connects to that named database
    and executes all Firestore operations without 404 errors.

    This is a scoped property-based test focused on the concrete failing case:
    - Named database exists (e.g., "test-database-name")
    - database_id is configured via environment variable
    - All Firestore operations should work without 404 errors
    """

    def setUp(self):
        """Set up test environment with named database configuration."""
        # Store original environment
        self.original_env = os.environ.copy()

        # Configure a named Firestore database (simulating Terraform deployment)
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"
        os.environ["AK_SESSION__FIRESTORE__PROJECT_ID"] = "test-project"
        os.environ["AK_SESSION__FIRESTORE__DATABASE_ID"] = "test-database-name"
        os.environ["AK_SESSION__FIRESTORE__TTL"] = "3600"

        # Reset AKConfig to pick up new environment variables
        from agentkernel.core.config import AKConfig

        AKConfig._set()

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

        # Reset AKConfig
        from agentkernel.core.config import AKConfig

        AKConfig._set()

    @patch("google.cloud.firestore.Client")
    def test_named_database_connection_with_database_id(self, mock_client_class):
        """
        Test that FirestoreDriver connects to the named database when database_id is configured.

        EXPECTED BEHAVIOR (after fix):
        - firestore.Client() should be called with database="test-database-name"
        - All Firestore operations should succeed without 404 errors

        EXPECTED FAILURE (on unfixed code):
        - firestore.Client() is called WITHOUT database parameter
        - This causes connection to (default) database instead of named database
        - Operations would fail with 404 errors in real deployment
        """
        # Mock the Firestore client and its methods
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_document = MagicMock()
        mock_doc_ref = MagicMock()

        # Set up the mock chain
        mock_client_class.return_value = mock_client
        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_document
        mock_document.get.return_value = mock_doc_ref
        mock_doc_ref.exists = True
        mock_doc_ref.to_dict.return_value = {"test_key": b"test_value"}

        # Import and initialize FirestoreDriver
        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()

        # Trigger connection by accessing collection
        _ = driver.collection

        # CRITICAL ASSERTION: Verify firestore.Client was called with database parameter
        # This is the core of the bug - unfixed code does NOT pass database parameter
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]

        # The fix should pass database="test-database-name"
        # Unfixed code will NOT have 'database' in kwargs, causing this assertion to FAIL
        self.assertIn(
            "database",
            call_kwargs,
            "EXPECTED FAILURE: database parameter not passed to firestore.Client(). "
            "This confirms the bug exists - FirestoreDriver does not use database_id configuration.",
        )
        self.assertEqual(call_kwargs["database"], "test-database-name", "database parameter should match the configured database_id")

        # Also verify project_id is still passed (preservation requirement)
        self.assertIn("project", call_kwargs)
        self.assertEqual(call_kwargs["project"], "test-project")

    @patch("google.cloud.firestore.Client")
    def test_all_firestore_operations_with_named_database(self, mock_client_class):
        """
        Test that all Firestore operations (put, get, get_all_keys, delete_all) work
        correctly when database_id is configured.

        EXPECTED BEHAVIOR (after fix):
        - All operations should execute without errors
        - Operations should target the named database

        EXPECTED FAILURE (on unfixed code):
        - Operations would fail with 404 errors in real deployment
        - Mock test may pass but real deployment would fail
        """
        # Mock the Firestore client and its methods
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_document = MagicMock()
        mock_doc_ref = MagicMock()

        # Set up the mock chain
        mock_client_class.return_value = mock_client
        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_document
        mock_document.get.return_value = mock_doc_ref
        mock_doc_ref.exists = True
        mock_doc_ref.to_dict.return_value = {"key1": b"value1", "key2": b"value2"}
        mock_collection.limit.return_value = mock_collection
        mock_collection.stream.return_value = []

        # Import and initialize FirestoreDriver
        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()

        # Test put operation
        driver.put("session1", "key1", b"value1")
        mock_document.set.assert_called()

        # Test get operation
        result = driver.get("session1", "key1")
        self.assertIsNotNone(result)

        # Test get_all_keys operation
        keys = driver.get_all_keys("session1")
        self.assertIsInstance(keys, list)

        # Test delete_all operation
        driver.delete_all()

        # Verify the client was initialized with database parameter
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]

        # This assertion will FAIL on unfixed code
        self.assertIn(
            "database",
            call_kwargs,
            "EXPECTED FAILURE: All operations should use named database connection. "
            "Unfixed code does not pass database parameter, causing 404 errors in real deployment.",
        )

    @patch("google.cloud.firestore.Client")
    def test_config_has_database_id_field(self, mock_client_class):
        """
        Test that _FirestoreConfig has a database_id field that can be read.

        EXPECTED BEHAVIOR (after fix):
        - _FirestoreConfig should have database_id field
        - database_id should be readable from environment variable

        EXPECTED FAILURE (on unfixed code):
        - _FirestoreConfig does not have database_id field
        - Configuration cannot be read
        """
        from agentkernel.core.config import AKConfig

        cfg = AKConfig.get().session.firestore

        # This assertion will FAIL on unfixed code because database_id field doesn't exist
        self.assertTrue(
            hasattr(cfg, "database_id"),
            "EXPECTED FAILURE: _FirestoreConfig missing database_id field. " "This confirms the bug - no way to configure database name.",
        )

        # Verify the value is correctly read from environment
        self.assertEqual(cfg.database_id, "test-database-name", "database_id should be read from AK_SESSION__FIRESTORE__DATABASE_ID")

    @patch("google.cloud.firestore.Client")
    def test_driver_stores_database_id(self, mock_client_class):
        """
        Test that FirestoreDriver reads and stores database_id from config.

        EXPECTED BEHAVIOR (after fix):
        - FirestoreDriver.__init__() should read cfg.database_id
        - Driver should store it for use in _connect()

        EXPECTED FAILURE (on unfixed code):
        - Driver does not read or store database_id
        """
        # Mock the Firestore client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()

        # This assertion will FAIL on unfixed code because _database_id attribute doesn't exist
        self.assertTrue(
            hasattr(driver, "_database_id"),
            "EXPECTED FAILURE: FirestoreDriver missing _database_id attribute. "
            "This confirms the bug - driver doesn't store database_id from config.",
        )

        # Verify the value matches the configuration
        self.assertEqual(driver._database_id, "test-database-name", "Driver should store database_id from config")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestFirestorePreservation(unittest.TestCase):
    """
    Property 2: Preservation - Default Database and Existing Configuration Behavior

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

    These tests observe and capture the CURRENT behavior on UNFIXED code for non-buggy
    inputs (deployments NOT using create_firestore_database = true).

    IMPORTANT: These tests should PASS on unfixed code - they document baseline behavior
    that must be preserved after the fix is implemented.

    Property-based testing approach: Generate many test cases to ensure preservation
    across the input domain.
    """

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.copy()

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

        # Reset AKConfig
        from agentkernel.core.config import AKConfig

        AKConfig._set()

    @patch("google.cloud.firestore.Client")
    def test_default_database_when_database_id_not_specified(self, mock_client_class):
        """
        Test that when database_id is NOT specified, connection defaults to (default) database.

        This is the baseline behavior that must be preserved for backward compatibility.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Configure Firestore WITHOUT database_id (typical existing deployment)
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"
        os.environ["AK_SESSION__FIRESTORE__PROJECT_ID"] = "test-project"
        # NOTE: AK_SESSION__FIRESTORE__DATABASE_ID is NOT set

        # Reset AKConfig to pick up new environment variables
        from agentkernel.core.config import AKConfig

        AKConfig._set()

        # Mock the Firestore client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()
        _ = driver.collection  # Trigger connection

        # BASELINE BEHAVIOR: When database_id is not specified, the client should
        # be initialized WITHOUT a database parameter, defaulting to (default)
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]

        # Current behavior: database parameter is NOT passed
        self.assertNotIn(
            "database",
            call_kwargs,
            "Baseline behavior: database parameter should NOT be passed when database_id is not configured. "
            "This allows client to default to (default) database.",
        )

        # Verify project_id is still passed (preservation requirement)
        self.assertIn("project", call_kwargs)
        self.assertEqual(call_kwargs["project"], "test-project")

    @patch("google.cloud.firestore.Client")
    def test_project_id_passed_to_client(self, mock_client_class):
        """
        Test that when project_id is specified, it is passed to the Firestore client.

        This behavior must be preserved after the fix.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Configure with project_id
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"
        os.environ["AK_SESSION__FIRESTORE__PROJECT_ID"] = "my-gcp-project"

        from agentkernel.core.config import AKConfig

        AKConfig._set()

        # Mock the Firestore client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()
        _ = driver.collection  # Trigger connection

        # BASELINE BEHAVIOR: project_id should be passed to client
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]

        self.assertIn("project", call_kwargs, "Baseline behavior: project parameter must be passed when project_id is configured")
        self.assertEqual(call_kwargs["project"], "my-gcp-project")

    @patch("google.cloud.firestore.Client")
    def test_ttl_configuration_sets_expiry_time(self, mock_client_class):
        """
        Test that when TTL is configured, expiry_time fields are set on documents.

        This behavior must be preserved after the fix.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Configure with TTL
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"
        os.environ["AK_SESSION__FIRESTORE__TTL"] = "7200"  # 2 hours

        from agentkernel.core.config import AKConfig

        AKConfig._set()

        # Mock the Firestore client and document
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_document = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_document

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()

        # Perform a put operation
        driver.put("session1", "key1", b"value1")

        # BASELINE BEHAVIOR: expiry_time should be set when TTL is configured
        mock_document.set.assert_called_once()
        call_args = mock_document.set.call_args[0]
        data = call_args[0]

        self.assertIn("expiry_time", data, "Baseline behavior: expiry_time must be set when TTL is configured")
        self.assertIsInstance(data["expiry_time"], datetime.datetime, "expiry_time should be a datetime object")
        self.assertIn("key1", data, "Session key should be in the data")

    @patch("google.cloud.firestore.Client")
    def test_all_firestore_operations_work(self, mock_client_class):
        """
        Test that all Firestore operations (put, get, get_all_keys, delete_all) work correctly.

        This behavior must be preserved after the fix.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Configure Firestore
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"

        from agentkernel.core.config import AKConfig

        AKConfig._set()

        # Mock the Firestore client and its methods
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_document = MagicMock()
        mock_doc_ref = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_document
        mock_document.get.return_value = mock_doc_ref
        mock_doc_ref.exists = True
        mock_doc_ref.to_dict.return_value = {"key1": b"value1", "key2": b"value2"}
        mock_collection.limit.return_value = mock_collection
        mock_collection.stream.return_value = []

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()

        # Test put operation
        driver.put("session1", "key1", b"value1")
        mock_document.set.assert_called()

        # Test get operation
        result = driver.get("session1", "key1")
        self.assertEqual(result, b"value1")

        # Test get_all_keys operation
        keys = driver.get_all_keys("session1")
        self.assertIsInstance(keys, list)
        self.assertIn("key1", keys)
        self.assertIn("key2", keys)

        # Test delete_all operation
        driver.delete_all()
        mock_collection.limit.assert_called()

        # BASELINE BEHAVIOR: All operations should work without errors

    @patch("google.cloud.firestore.Client")
    def test_existing_config_fields_work(self, mock_client_class):
        """
        Test that all existing _FirestoreConfig fields (collection_name, project_id, ttl)
        continue to work as before.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Configure all existing fields
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "custom_collection"
        os.environ["AK_SESSION__FIRESTORE__PROJECT_ID"] = "custom-project"
        os.environ["AK_SESSION__FIRESTORE__TTL"] = "3600"

        from agentkernel.core.config import AKConfig

        AKConfig._set()

        cfg = AKConfig.get().session.firestore

        # BASELINE BEHAVIOR: All existing fields should be readable
        self.assertEqual(cfg.collection_name, "custom_collection")
        self.assertEqual(cfg.project_id, "custom-project")
        self.assertEqual(cfg.ttl, 3600)

        # Mock the Firestore client
        mock_client = MagicMock()
        mock_collection = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.collection.return_value = mock_collection

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()

        # Verify driver uses the configured values
        self.assertEqual(driver._collection_name, "custom_collection")
        self.assertEqual(driver._project_id, "custom-project")
        self.assertEqual(driver._ttl, 3600)

        # Trigger connection
        _ = driver.collection

        # Verify collection is accessed with correct name
        mock_client.collection.assert_called_with("custom_collection")

    @patch("google.cloud.firestore.Client")
    def test_no_database_id_in_unfixed_config(self, mock_client_class):
        """
        Test that the current _FirestoreConfig does NOT have a database_id field.

        This documents the current state before the fix. After the fix, this test
        will need to be updated or removed.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms current state)
        """
        # Configure Firestore
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"

        from agentkernel.core.config import AKConfig

        AKConfig._set()

        cfg = AKConfig.get().session.firestore

        # CURRENT STATE: database_id field does not exist on unfixed code
        # This test documents the baseline - after fix, this will change
        self.assertFalse(
            hasattr(cfg, "database_id"), "Current state: _FirestoreConfig does not have database_id field. " "This is expected on unfixed code."
        )

    @patch("google.cloud.firestore.Client")
    def test_reserved_fields_excluded_from_keys(self, mock_client_class):
        """
        Test that reserved fields (like expiry_time) are excluded from get_all_keys.

        This behavior must be preserved after the fix.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Configure Firestore
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"

        from agentkernel.core.config import AKConfig

        AKConfig._set()

        # Mock the Firestore client
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_document = MagicMock()
        mock_doc_ref = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_document
        mock_document.get.return_value = mock_doc_ref
        mock_doc_ref.exists = True
        # Document has both session keys and reserved fields
        mock_doc_ref.to_dict.return_value = {"key1": b"value1", "key2": b"value2", "expiry_time": datetime.datetime.now(datetime.timezone.utc)}

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()

        # Get all keys
        keys = driver.get_all_keys("session1")

        # BASELINE BEHAVIOR: expiry_time should be excluded from keys
        self.assertIn("key1", keys)
        self.assertIn("key2", keys)
        self.assertNotIn("expiry_time", keys, "Baseline behavior: expiry_time should be excluded from session keys")


class TestFirestorePreservationPropertyBased(unittest.TestCase):
    """
    Property-based tests for preservation requirements.

    These tests generate multiple test cases to provide stronger guarantees
    that the fix preserves existing behavior across the input domain.
    """

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.copy()

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

        from agentkernel.core.config import AKConfig

        AKConfig._set()

    @patch("google.cloud.firestore.Client")
    def test_various_collection_names(self, mock_client_class):
        """
        Property: For any valid collection_name, the driver should use it correctly.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Test with various collection names
        collection_names = ["ak_sessions", "custom_sessions", "prod_sessions", "test-collection", "collection_123"]

        for collection_name in collection_names:
            with self.subTest(collection_name=collection_name):
                # Reset environment
                os.environ.clear()
                os.environ.update(self.original_env)

                # Configure with this collection name
                os.environ["AK_SESSION__TYPE"] = "firestore"
                os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = collection_name

                from agentkernel.core.config import AKConfig

                AKConfig._set()

                # Mock the Firestore client
                mock_client = MagicMock()
                mock_collection = MagicMock()
                mock_client_class.return_value = mock_client
                mock_client.collection.return_value = mock_collection

                from agentkernel.core.session.firestore import FirestoreDriver

                driver = FirestoreDriver()
                _ = driver.collection

                # Verify collection is accessed with correct name
                mock_client.collection.assert_called_with(collection_name)

                # Reset for next iteration
                mock_client_class.reset_mock()

    @patch("google.cloud.firestore.Client")
    def test_various_ttl_values(self, mock_client_class):
        """
        Property: For any valid TTL value, expiry_time should be set correctly.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Test with various TTL values
        ttl_values = [0, 60, 3600, 7200, 86400, 604800]

        for ttl in ttl_values:
            with self.subTest(ttl=ttl):
                # Reset environment
                os.environ.clear()
                os.environ.update(self.original_env)

                # Configure with this TTL
                os.environ["AK_SESSION__TYPE"] = "firestore"
                os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"
                os.environ["AK_SESSION__FIRESTORE__TTL"] = str(ttl)

                from agentkernel.core.config import AKConfig

                AKConfig._set()

                # Mock the Firestore client
                mock_client = MagicMock()
                mock_collection = MagicMock()
                mock_document = MagicMock()
                mock_client_class.return_value = mock_client
                mock_client.collection.return_value = mock_collection
                mock_collection.document.return_value = mock_document

                from agentkernel.core.session.firestore import FirestoreDriver

                driver = FirestoreDriver()
                driver.put("session1", "key1", b"value1")

                # Verify expiry_time behavior based on TTL
                mock_document.set.assert_called_once()
                call_args = mock_document.set.call_args[0]
                data = call_args[0]

                if ttl > 0:
                    self.assertIn("expiry_time", data, f"expiry_time should be set when TTL={ttl}")
                else:
                    # When TTL is 0, expiry_time should not be set
                    self.assertNotIn("expiry_time", data, f"expiry_time should NOT be set when TTL={ttl}")

                # Reset for next iteration
                mock_client_class.reset_mock()

    @patch("google.cloud.firestore.Client")
    def test_various_project_ids(self, mock_client_class):
        """
        Property: For any valid project_id, it should be passed to the client.

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Test with various project IDs
        project_ids = ["my-project", "prod-project-123", "test-env", "gcp-project-456"]

        for project_id in project_ids:
            with self.subTest(project_id=project_id):
                # Reset environment
                os.environ.clear()
                os.environ.update(self.original_env)

                # Configure with this project ID
                os.environ["AK_SESSION__TYPE"] = "firestore"
                os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"
                os.environ["AK_SESSION__FIRESTORE__PROJECT_ID"] = project_id

                from agentkernel.core.config import AKConfig

                AKConfig._set()

                # Mock the Firestore client
                mock_client = MagicMock()
                mock_client_class.return_value = mock_client

                from agentkernel.core.session.firestore import FirestoreDriver

                driver = FirestoreDriver()
                _ = driver.collection

                # Verify project is passed to client
                mock_client_class.assert_called_once()
                call_kwargs = mock_client_class.call_args[1]
                self.assertIn("project", call_kwargs)
                self.assertEqual(call_kwargs["project"], project_id)

                # Reset for next iteration
                mock_client_class.reset_mock()

    @patch("google.cloud.firestore.Client")
    def test_no_project_id_specified(self, mock_client_class):
        """
        Property: When project_id is not specified, client should be initialized
        without project parameter (allowing ADC to infer it).

        EXPECTED OUTCOME: Test PASSES on unfixed code (confirms baseline behavior)
        """
        # Configure WITHOUT project_id
        os.environ["AK_SESSION__TYPE"] = "firestore"
        os.environ["AK_SESSION__FIRESTORE__COLLECTION_NAME"] = "test_sessions"
        # NOTE: AK_SESSION__FIRESTORE__PROJECT_ID is NOT set

        from agentkernel.core.config import AKConfig

        AKConfig._set()

        # Mock the Firestore client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        from agentkernel.core.session.firestore import FirestoreDriver

        driver = FirestoreDriver()
        _ = driver.collection

        # BASELINE BEHAVIOR: When project_id is None, project parameter should not be passed
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]

        # Current behavior: project parameter is NOT passed when project_id is None
        self.assertNotIn("project", call_kwargs, "Baseline behavior: project parameter should NOT be passed when project_id is not configured")
