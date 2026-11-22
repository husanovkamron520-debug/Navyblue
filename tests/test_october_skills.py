import unittest

from october_skills import available_skills, build_skill_context, select_skills


class OctoberSkillsTests(unittest.TestCase):
    def test_routes_each_specialist_area(self):
        cases = {
            "logistics": "Supply chain ombor inventory KPI tahlili",
            "presentation": "12 slaydli PowerPoint taqdimot tayyorla",
            "research": "GitHub repolarni internetdan qidirib taqqosla",
            "study": "IELTS writing mashqini tushuntirib ber",
            "development": "Telegram botdagi Python kod xatosini tuzat",
            "productivity": "Ertaga deadline uchun vazifa va eslatma qo'sh",
        }
        for expected, message in cases.items():
            with self.subTest(skill=expected):
                self.assertIn(expected, select_skills(message))

    def test_unrelated_message_does_not_load_a_skill(self):
        self.assertEqual([], select_skills("Salom, qalaysan?"))

    def test_skill_count_is_bounded(self):
        message = "Python Telegram bot GitHub repo taqdimot slayd logistika"
        self.assertLessEqual(len(select_skills(message)), 2)

    def test_context_is_only_added_for_matching_messages(self):
        self.assertEqual("", build_skill_context("Oddiy salom"))
        self.assertIn("Taqdimot", build_skill_context("PowerPoint taqdimot kerak"))

    def test_registry_has_six_skills(self):
        self.assertEqual(6, len(available_skills()))


if __name__ == "__main__":
    unittest.main()
