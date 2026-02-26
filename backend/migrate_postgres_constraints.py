"""
PostgreSQL-safe constraint/index migration for MacQuiz.

This script checks for duplicate data first, then applies unique indexes only when
safe. It can run in dry-run mode (default) to report exactly what would happen.
"""

import argparse
from dataclasses import dataclass

from sqlalchemy import text

from app.db.database import engine


@dataclass
class ConstraintCheck:
    name: str
    duplicate_count_sql: str
    create_sql: str
    description: str


UNIQUE_CHECKS = [
    ConstraintCheck(
        name="uq_answers_attempt_question",
        description="One answer per question in each attempt",
        duplicate_count_sql="""
            SELECT COUNT(*)
            FROM (
                SELECT attempt_id, question_id
                FROM public.answers
                GROUP BY attempt_id, question_id
                HAVING COUNT(*) > 1
            ) d
        """,
        create_sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_answers_attempt_question
            ON public.answers (attempt_id, question_id)
        """,
    ),
    ConstraintCheck(
        name="uq_quiz_assignments_quiz_student",
        description="One assignment per student per quiz",
        duplicate_count_sql="""
            SELECT COUNT(*)
            FROM (
                SELECT quiz_id, student_id
                FROM public.quiz_assignments
                GROUP BY quiz_id, student_id
                HAVING COUNT(*) > 1
            ) d
        """,
        create_sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_quiz_assignments_quiz_student
            ON public.quiz_assignments (quiz_id, student_id)
        """,
    ),
    ConstraintCheck(
        name="uq_revoked_tokens_jti",
        description="JWT jti must be globally unique",
        duplicate_count_sql="""
            SELECT COUNT(*)
            FROM (
                SELECT jti
                FROM public.revoked_tokens
                GROUP BY jti
                HAVING COUNT(*) > 1
            ) d
        """,
        create_sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_revoked_tokens_jti
            ON public.revoked_tokens (jti)
        """,
    ),
    ConstraintCheck(
        name="uq_user_token_blocks_user_id",
        description="Single token-block row per user",
        duplicate_count_sql="""
            SELECT COUNT(*)
            FROM (
                SELECT user_id
                FROM public.user_token_blocks
                GROUP BY user_id
                HAVING COUNT(*) > 1
            ) d
        """,
        create_sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_user_token_blocks_user_id
            ON public.user_token_blocks (user_id)
        """,
    ),
    ConstraintCheck(
        name="uq_users_email",
        description="Email must be unique",
        duplicate_count_sql="""
            SELECT COUNT(*)
            FROM (
                SELECT email
                FROM public.users
                GROUP BY email
                HAVING COUNT(*) > 1
            ) d
        """,
        create_sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email
            ON public.users (email)
        """,
    ),
    ConstraintCheck(
        name="uq_users_student_id",
        description="Student/teacher user ID must be unique when present",
        duplicate_count_sql="""
            SELECT COUNT(*)
            FROM (
                SELECT student_id
                FROM public.users
                WHERE student_id IS NOT NULL
                GROUP BY student_id
                HAVING COUNT(*) > 1
            ) d
        """,
        create_sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_users_student_id
            ON public.users (student_id)
            WHERE student_id IS NOT NULL
        """,
    ),
]

NON_UNIQUE_INDEXES = [
    (
        "ix_answers_attempt_id",
        "CREATE INDEX IF NOT EXISTS ix_answers_attempt_id ON public.answers (attempt_id)",
    ),
    (
        "ix_answers_question_id",
        "CREATE INDEX IF NOT EXISTS ix_answers_question_id ON public.answers (question_id)",
    ),
    (
        "ix_question_bank_subject_id",
        "CREATE INDEX IF NOT EXISTS ix_question_bank_subject_id ON public.question_bank (subject_id)",
    ),
    (
        "ix_question_bank_creator_id",
        "CREATE INDEX IF NOT EXISTS ix_question_bank_creator_id ON public.question_bank (creator_id)",
    ),
    (
        "ix_questions_quiz_id",
        "CREATE INDEX IF NOT EXISTS ix_questions_quiz_id ON public.questions (quiz_id)",
    ),
    (
        "ix_questions_question_bank_id",
        "CREATE INDEX IF NOT EXISTS ix_questions_question_bank_id ON public.questions (question_bank_id)",
    ),
    (
        "ix_quiz_attempts_quiz_id",
        "CREATE INDEX IF NOT EXISTS ix_quiz_attempts_quiz_id ON public.quiz_attempts (quiz_id)",
    ),
    (
        "ix_quiz_attempts_student_id",
        "CREATE INDEX IF NOT EXISTS ix_quiz_attempts_student_id ON public.quiz_attempts (student_id)",
    ),
    (
        "ix_quizzes_creator_id",
        "CREATE INDEX IF NOT EXISTS ix_quizzes_creator_id ON public.quizzes (creator_id)",
    ),
    (
        "ix_quizzes_subject_id",
        "CREATE INDEX IF NOT EXISTS ix_quizzes_subject_id ON public.quizzes (subject_id)",
    ),
    (
        "ix_subjects_creator_id",
        "CREATE INDEX IF NOT EXISTS ix_subjects_creator_id ON public.subjects (creator_id)",
    ),
]


def _scalar(connection, sql: str) -> int:
    result = connection.execute(text(sql)).scalar()
    return int(result or 0)


def run(apply_changes: bool) -> int:
    if engine.dialect.name != "postgresql":
        print(f"❌ This script is for PostgreSQL only. Current dialect: {engine.dialect.name}")
        return 2

    print("🔍 Running PostgreSQL constraint pre-checks...")

    blocked = []
    ready = []

    with engine.begin() as connection:
        for check in UNIQUE_CHECKS:
            duplicate_groups = _scalar(connection, check.duplicate_count_sql)
            if duplicate_groups > 0:
                blocked.append((check, duplicate_groups))
            else:
                ready.append(check)

    if blocked:
        print("\n⚠️  Duplicate data detected. These unique indexes are blocked:")
        for check, count in blocked:
            print(f"  - {check.name}: {count} duplicate group(s) found ({check.description})")
    else:
        print("\n✅ No duplicate groups found for targeted unique constraints")

    print("\n📋 Planned unique indexes:")
    for check in UNIQUE_CHECKS:
        status = "BLOCKED" if any(item[0].name == check.name for item in blocked) else "READY"
        print(f"  - {check.name}: {status}")

    if not apply_changes:
        print("\nℹ️  Dry run only. Re-run with --apply to execute safe index creation.")
        return 1 if blocked else 0

    print("\n🚀 Applying safe indexes...")
    with engine.begin() as connection:
        for check in ready:
            connection.execute(text(check.create_sql))
            print(f"  ✅ Applied {check.name}")

        for index_name, create_sql in NON_UNIQUE_INDEXES:
            connection.execute(text(create_sql))
            print(f"  ✅ Ensured {index_name}")

    if blocked:
        print("\n⚠️  Migration applied partially. Resolve duplicates, then re-run with --apply.")
        return 1

    print("\n🎉 All targeted PostgreSQL constraints/indexes are applied safely.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Safe PostgreSQL constraint/index migration")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply indexes that pass duplicate pre-checks",
    )
    args = parser.parse_args()
    raise SystemExit(run(apply_changes=args.apply))


if __name__ == "__main__":
    main()
