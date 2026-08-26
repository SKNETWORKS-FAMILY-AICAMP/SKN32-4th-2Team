"""Unit tests for safe target/legacy database configuration helpers."""

from django.test import SimpleTestCase

from config.settings import is_same_mysql_database, mysql_database_config


class MySQLDatabaseConfigurationTests(SimpleTestCase):
    def test_parser_decodes_url_values_and_uses_utf8mb4_by_default(self):
        config = mysql_database_config(
            "mysql+pymysql://legacy%20user:legacy%2Fpassword@legacy-host:3310/"
            "legacy_db",
            variable_name="LEGACY_DATABASE_URL",
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.mysql")
        self.assertEqual(config["NAME"], "legacy_db")
        self.assertEqual(config["USER"], "legacy user")
        self.assertEqual(config["PASSWORD"], "legacy/password")
        self.assertEqual(config["HOST"], "legacy-host")
        self.assertEqual(config["PORT"], 3310)
        self.assertEqual(config["OPTIONS"]["charset"], "utf8mb4")

    def test_same_database_check_uses_host_port_and_name(self):
        target = mysql_database_config(
            "mysql://target:pw@MYSQL:3306/rag_chatbot_v4",
            variable_name="DATABASE_URL",
        )
        same_target = mysql_database_config(
            "mysql://legacy:pw@mysql/rag_chatbot_v4",
            variable_name="LEGACY_DATABASE_URL",
        )
        other_target = mysql_database_config(
            "mysql://legacy:pw@mysql/rag_chatbot",
            variable_name="LEGACY_DATABASE_URL",
        )

        self.assertTrue(is_same_mysql_database(target, same_target))
        self.assertFalse(is_same_mysql_database(target, other_target))

    def test_parser_rejects_non_mysql_url(self):
        with self.assertRaisesMessage(
            ValueError,
            "LEGACY_DATABASE_URL must use a MySQL URL.",
        ):
            mysql_database_config(
                "sqlite:///legacy.db",
                variable_name="LEGACY_DATABASE_URL",
            )
