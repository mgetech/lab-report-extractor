using Testcontainers.PostgreSql;

namespace LabReportExtractor.Api.Tests.Data;

/// <summary>
/// Starts one disposable Postgres container (via Testcontainers) for every test in the
/// <see cref="PostgresCollection"/>, so repository/endpoint tests exercise the real EF Core -&gt;
/// Npgsql mapping — including the owned-entity/JSONB mapping in <c>LabReportDbContext</c> — rather
/// than an in-memory provider that would silently accept things Postgres wouldn't.
/// </summary>
public sealed class PostgresFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer _container = new PostgreSqlBuilder("postgres:16-alpine")
        .WithDatabase("labreports_test")
        .WithUsername("postgres")
        .WithPassword("postgres")
        .Build();

    public string ConnectionString => _container.GetConnectionString();

    public Task InitializeAsync() => _container.StartAsync();

    public Task DisposeAsync() => _container.DisposeAsync().AsTask();
}

/// <summary>
/// Groups every test class that needs <see cref="PostgresFixture"/> so xUnit starts one container
/// and runs them sequentially against it (no parallel schema reset races).
/// </summary>
[CollectionDefinition(Name)]
public sealed class PostgresCollection : ICollectionFixture<PostgresFixture>
{
    public const string Name = "Postgres";
}