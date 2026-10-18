import pytest
from sqlalchemy import select
from app.localization.i18n import i18n, t
from app.services.user_service import UserService
from app.services.card_generator import generate_player_share_card
from app.services.analytics_service import AnalyticsService
from app.services.demo_service import DemoService
from app.models.game import GameAccount
from app.models.dispute import Dispute
from app.models.hub import Hub, HubMembership
from app.models.match import Match, MatchReport
from app.models.ratings import PlatformRating
from app.models.tournament import Tournament
from app.services.rating_service import RatingService
from app.auth.dependencies import get_managed_hub_ids, user_manages_hub

def test_translation_catalogs_and_fallbacks():
    # Canonical English keys
    en_keys = i18n.catalogs.get("en", {})
    assert len(en_keys) > 30

    # Amharic keys
    am_keys = i18n.catalogs.get("am", {})
    assert len(am_keys) > 30

    # Verify fallback to English when key doesn't exist
    assert t("non_existent_key_123") == "non_existent_key_123"

    # Verify missing keys check
    missing = i18n.check_missing_keys()
    assert missing == {}
    for catalog in i18n.catalogs.values():
        assert set(catalog) == set(en_keys)

def test_share_card_generator():
    png_bytes = generate_player_share_card(
        display_name="Desta Kebede",
        public_id="et-desta-test",
        city="Addis Ababa",
        tier="Gold",
        elo=1550.0,
        matches_played=20,
        wins=14,
        verified_accounts=["lichess:desta_et"]
    )
    # Check PNG magic header bytes
    assert png_bytes[:8] == b'\x89PNG\r\n\x1a\n'
    assert len(png_bytes) > 5000

@pytest.mark.asyncio
async def test_full_e2e_registration_and_analytics(client, db_session):
    # 1. Register player
    reg_resp = await client.post("/api/auth/register", json={
        "username": "e2e_tester",
        "display_name": "E2E Tester",
        "city": "Addis Ababa",
        "language": "am"
    })
    assert reg_resp.status_code == 200
    public_id = reg_resp.json()["public_identifier"]

    # 2. Public Gamer Passport without login
    passport_resp = await client.get(f"/p/{public_id}")
    assert passport_resp.status_code == 200
    assert "E2E Tester" in passport_resp.text
    assert 'class="profile-hero"' in passport_resp.text
    assert 'class="profile-stats"' in passport_resp.text

    dashboard_resp = await client.get("/dashboard")
    assert dashboard_resp.status_code == 200
    assert "Welcome back" in dashboard_resp.text
    assert 'class="dashboard-rank-card"' in dashboard_resp.text

    # 3. Share card download
    card_resp = await client.get(f"/p/{public_id}/card.png")
    assert card_resp.status_code == 200
    assert card_resp.headers["content-type"] == "image/png"

    # 4. Analytics metrics
    analytics_resp = await client.get("/api/analytics")
    assert analytics_resp.status_code == 200
    metrics = analytics_resp.json()
    assert metrics["total_registrations"] >= 1
    assert "match_completion_rate" in metrics

@pytest.mark.asyncio
async def test_leaderboard_renders_ranked_player_cards(client, db_session):
    await UserService.register_user(db_session, "ranking_ui_player", "Ranking UI Player")

    response = await client.get("/leaderboards")

    assert response.status_code == 200
    assert "Top players" in response.text
    assert "Full leaderboard" in response.text
    assert "Ranking UI Player" in response.text

@pytest.mark.asyncio
async def test_homepage_renders_competitive_lobby(client):
    response = await client.get("/")

    assert response.status_code == 200
    assert "ETHIOPIA'S COMPETITIVE PLAYER HUB" in response.text
    assert "YOUR NEXT LEVEL" in response.text

@pytest.mark.asyncio
async def test_demo_safe_reset_isolation(db_session):
    # Create real pilot user (is_demo=False)
    real_user = await UserService.register_user(
        db_session, "real_pilot_gamer", "Real Pilot Gamer", is_demo=False
    )
    # Seed demo data
    await DemoService.seed_demo_data(db_session)

    # Safe demo wipe
    wipe_res = await DemoService.safe_demo_wipe(db_session)
    assert wipe_res["status"] == "success"

    # Verify real pilot user STILL EXISTS!
    from sqlalchemy import select
    from app.models.user import User
    stmt = select(User).where(User.username == "real_pilot_gamer")
    found_real = (await db_session.execute(stmt)).scalar_one_or_none()
    assert found_real is not None
    assert found_real.display_name == "Real Pilot Gamer"

@pytest.mark.asyncio
async def test_demo_seed_includes_captain_review_dispute(db_session):
    await DemoService.seed_demo_data(db_session)

    dispute = (await db_session.execute(
        select(Dispute).where(Dispute.status == "open")
    )).scalar_one()
    match = (await db_session.execute(select(Match).where(Match.id == dispute.match_id))).scalar_one()
    tournament = (await db_session.execute(
        select(Tournament).where(Tournament.id == match.tournament_id)
    )).scalar_one()
    reports = (await db_session.execute(
        select(MatchReport).where(MatchReport.match_id == match.id)
    )).scalars().all()

    assert match.status == "disputed"
    assert tournament.slug == "captain-review-demo"
    assert tournament.is_demo
    assert len(reports) == 2

@pytest.mark.asyncio
async def test_game_account_verification_is_owner_scoped(db_session):
    owner = await UserService.register_user(db_session, "account_owner", "Account Owner")
    other_player = await UserService.register_user(db_session, "other_player", "Other Player")
    account = GameAccount(
        user_id=owner.id,
        game_key="lichess",
        external_username="owner_lichess",
        status="pending_verification",
        bio_code="GB-TEST"
    )
    db_session.add(account)
    await db_session.commit()

    verified, message = await UserService.verify_game_account(db_session, account.id, other_player.id)

    assert not verified
    assert message == "Game account record not found."
    assert account.status == "pending_verification"

@pytest.mark.asyncio
async def test_game_account_link_requires_consent(client):
    await client.post("/api/auth/register", json={
        "username": "consent_player",
        "display_name": "Consent Player",
        "city": "Addis Ababa",
        "language": "en"
    })

    response = await client.post("/api/games/link", json={
        "game_key": "lichess",
        "external_username": "consent_lichess"
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "Account-linking consent is required."

    approved_response = await client.post("/api/games/link", json={
        "game_key": "lichess",
        "external_username": "consent_lichess",
        "consent": True
    })
    assert approved_response.status_code == 200
    assert approved_response.json()["verification_code"].startswith("GB-")

@pytest.mark.asyncio
async def test_demo_reset_requires_admin(client):
    response = await client.post("/api/demo/reset")

    assert response.status_code == 401

@pytest.mark.asyncio
async def test_leaderboard_search_preserves_global_rank(db_session):
    players = [
        await UserService.register_user(db_session, username, name)
        for username, name in [
            ("rank_first", "Rank First"),
            ("rank_second", "Rank Second"),
            ("rank_third", "Rank Third")
        ]
    ]
    for player, elo in zip(players, [1600, 1500, 1400]):
        rating = (await db_session.execute(
            select(PlatformRating).where(
                PlatformRating.user_id == player.id,
                PlatformRating.game_key == "lichess",
                PlatformRating.mode == "rapid"
            )
        )).scalar_one()
        rating.elo = elo
    await db_session.commit()

    results = await RatingService.get_platform_leaderboard(
        db_session, game_key="lichess", mode="rapid", search="rank_third"
    )

    assert len(results) == 1
    assert results[0]["display_name"] == "Rank Third"
    assert results[0]["rank"] == 3

@pytest.mark.asyncio
async def test_captain_permissions_are_limited_to_membership_hubs(db_session):
    captain = await UserService.register_user(db_session, "bole_captain", "Bole Captain", role="hub_captain")
    admin = await UserService.register_user(db_session, "platform_admin", "Platform Admin", role="super_admin")
    assigned_hub = Hub(name="Bole Test Hub", slug="bole-test-hub", city="Addis Ababa")
    other_hub = Hub(name="Hawassa Test Hub", slug="hawassa-test-hub", city="Hawassa")
    db_session.add_all([assigned_hub, other_hub])
    await db_session.flush()
    db_session.add(HubMembership(user_id=captain.id, hub_id=assigned_hub.id, role="captain"))
    await db_session.commit()

    assert await get_managed_hub_ids(db_session, captain) == [assigned_hub.id]
    assert await user_manages_hub(db_session, captain, assigned_hub.id)
    assert not await user_manages_hub(db_session, captain, other_hub.id)
    assert await get_managed_hub_ids(db_session, admin) is None
