from haotian.collectors.github_trending import GithubTrendingCollector


def test_parse_trending_html_extracts_expected_repository_fields() -> None:
    html = """
    <article class="Box-row">
      <h2>
        <a href="/openai/codex"> openai / codex </a>
      </h2>
      <p> AI coding agent for software tasks. </p>
      <div>
        <span itemprop="programmingLanguage">Python</span>
        <a href="/openai/codex/stargazers">12,345</a>
        <a href="/openai/codex/forks">678</a>
      </div>
    </article>
    """

    repos = GithubTrendingCollector().parse_trending_html(
        html=html,
        period="daily",
        snapshot_date="2026-03-20",
    )

    assert len(repos) == 1
    repo = repos[0]
    assert repo.snapshot_date == "2026-03-20"
    assert repo.period == "daily"
    assert repo.rank == 1
    assert repo.repo_full_name == "openai/codex"
    assert repo.repo_url == "https://github.com/openai/codex"
    assert repo.description == "AI coding agent for software tasks."
    assert repo.language == "Python"
    assert repo.stars == 12345
    assert repo.forks == 678


def test_parse_trending_html_supports_missing_optional_fields_and_k_suffix() -> None:
    html = """
    <article class="Box-row">
      <h2><a href="/psf/requests"> psf / requests </a></h2>
      <div>
        <a href="/psf/requests/stargazers">1.2k</a>
        <a href="/psf/requests/forks">3.4k</a>
      </div>
    </article>
    <article class="Box-row">
      <h2><a href="/pallets/flask"> pallets / flask </a></h2>
      <p> A lightweight WSGI web application framework. </p>
      <div>
        <span itemprop="programmingLanguage">Python</span>
        <a href="/pallets/flask/stargazers">2m</a>
      </div>
    </article>
    """

    repos = GithubTrendingCollector().parse_trending_html(
        html=html,
        period="weekly",
        snapshot_date="2026-03-20",
    )

    assert [repo.rank for repo in repos] == [1, 2]
    assert repos[0].repo_full_name == "psf/requests"
    assert repos[0].description is None
    assert repos[0].language is None
    assert repos[0].stars == 1200
    assert repos[0].forks == 3400

    assert repos[1].repo_full_name == "pallets/flask"
    assert repos[1].description == "A lightweight WSGI web application framework."
    assert repos[1].language == "Python"
    assert repos[1].stars == 2_000_000
    assert repos[1].forks is None
