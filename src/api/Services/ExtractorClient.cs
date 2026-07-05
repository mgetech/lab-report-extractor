using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using LabReportExtractor.Api.Models;

namespace LabReportExtractor.Api.Services;

/// <summary>
/// HTTP client for the stateless Python extraction engine's <c>POST /extract</c>
/// (Azure DI -> Azure OpenAI -> transform -> validate). This service never talks to Azure
/// directly — it only ever calls the extractor and persists what comes back.
/// </summary>
public sealed class ExtractorClient(HttpClient httpClient)
{
    /// <summary>Uploads a document to the extractor and returns the validated, structured report.</summary>
    /// <exception cref="ExtractorRequestException">The extractor rejected or failed to process the document.</exception>
    public async Task<LabReport> ExtractAsync(IFormFile file, CancellationToken cancellationToken = default)
    {
        using var content = new MultipartFormDataContent();
        await using var stream = file.OpenReadStream();
        using var streamContent = new StreamContent(stream);
        if (!string.IsNullOrEmpty(file.ContentType))
        {
            streamContent.Headers.ContentType = MediaTypeHeaderValue.Parse(file.ContentType);
        }

        content.Add(streamContent, "file", file.FileName);

        using var response = await httpClient.PostAsync("/extract", content, cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            var detail = await ReadErrorDetailAsync(response, cancellationToken);
            throw new ExtractorRequestException((int)response.StatusCode, detail);
        }

        var report = await response.Content.ReadFromJsonAsync<LabReport>(cancellationToken);
        return report ?? throw new ExtractorRequestException((int)response.StatusCode, "Extractor returned an empty response.");
    }

    /// <summary>Checks that the extractor process is up (its <c>/health</c>, not its own <c>/ready</c> — we only need to know it's reachable, not whether its Azure dependencies are).</summary>
    /// <exception cref="ExtractorRequestException">The extractor is unreachable or unhealthy.</exception>
    public async Task PingAsync(CancellationToken cancellationToken = default)
    {
        using var response = await httpClient.GetAsync("/health", cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new ExtractorRequestException((int)response.StatusCode, response.ReasonPhrase ?? "Extractor health check failed.");
        }
    }

    private static async Task<string> ReadErrorDetailAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        try
        {
            var error = await response.Content.ReadFromJsonAsync<FastApiError>(cancellationToken);
            return error?.Detail ?? response.ReasonPhrase ?? "Unknown extractor error.";
        }
        catch (Exception ex) when (ex is JsonException or NotSupportedException)
        {
            return response.ReasonPhrase ?? "Unknown extractor error.";
        }
    }

    /// <summary>Shape of a FastAPI <c>HTTPException</c> response body.</summary>
    private sealed record FastApiError(string? Detail);
}

/// <summary>Thrown when the extractor rejects or fails to process a document.</summary>
public sealed class ExtractorRequestException(int statusCode, string detail) : Exception(detail)
{
    /// <summary>The extractor's HTTP status code (422 = unreadable document, 502 = LLM failure).</summary>
    public int StatusCode { get; } = statusCode;
}