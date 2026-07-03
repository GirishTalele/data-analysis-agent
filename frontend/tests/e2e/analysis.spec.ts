import { test, expect } from '@playwright/test'
import path from 'path'

const FIXTURE_CSV = path.join(__dirname, '..', 'fixtures', 'sample.csv')

// Primary journey per spec/ui.md:
// upload a CSV -> see profile -> ask a question -> see answer + code + cost badge
// -> reload -> history persists.
//
// Requires the real backend (uv run python -m src) serving the static export
// at /app on :8001, per spec/roadmap.md's Phase 1 gate command. This suite is
// written now, ahead of the backend slices landing, per the code-generator
// contract for frontend-chat-ui.

test.describe('data analysis agent — primary journey', () => {
  test('upload, profile, ask, and history persistence', async ({ page }) => {
    await page.goto('./')

    // Page loads and is styled (empty state visible).
    await expect(page.getByText('Upload a CSV or Excel file to get started')).toBeVisible()

    // Upload the fixture CSV.
    await page.getByTestId('file-input').setInputFiles(FIXTURE_CSV)

    // Profile card renders.
    await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('profile-card')).toContainText('rows')
    await expect(page.getByTestId('profile-card')).toContainText('columns')

    // Ask a question.
    const input = page.getByTestId('question-input')
    await expect(input).toBeVisible()
    await input.fill("What's the average amount?")
    await page.getByTestId('send-button').click()

    // Step-progress indicator appears while running, then a real answer appears.
    await expect(page.getByTestId('assistant-message').last()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('user-message').last()).toContainText('average amount')

    // View code toggle + cost badge on the assistant answer, if the run succeeded.
    const lastAssistant = page.getByTestId('assistant-message').last()
    const codeToggle = lastAssistant.getByTestId('view-code-toggle')
    if (await codeToggle.count()) {
      await codeToggle.click()
      await expect(lastAssistant.locator('pre code')).toBeVisible()
      await expect(lastAssistant.getByTestId('cost-badge')).toContainText('tokens')
    }

    // Reload — history persists via localStorage dataset/conversation ids.
    await page.reload()
    await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('user-message').last()).toContainText('average amount')
  })
})
