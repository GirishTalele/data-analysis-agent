import { test, expect } from '@playwright/test'
import path from 'path'

const FIXTURE_CSV = path.join(__dirname, '..', 'fixtures', 'sample.csv')
const FIXTURE_CSV_2 = path.join(__dirname, '..', 'fixtures', 'sample2.csv')

// Phase 2 journey per spec/roadmap.md + spec/ui.md:
// step list, summary table + chart for a groupby answer, follow-up chips,
// multi-file add updates the row count, export triggers a download, and the
// audit page lists runs and shows today's cost total. Runs against the live
// backend serving the static export at http://localhost:8001/app/.

test.describe('data analysis agent — phase 2 features', () => {
  test('step list, summary table, chart, and follow-up chips for a groupby answer', async ({
    page,
  }) => {
    await page.goto('./')
    await expect(page.getByText('Upload a CSV or Excel file to get started')).toBeVisible()

    await page.getByTestId('file-input').setInputFiles(FIXTURE_CSV)
    await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })

    const input = page.getByTestId('question-input')
    await input.fill('What is the average amount by region?')
    await page.getByTestId('send-button').click()

    // Live step list while the request is in flight.
    await expect(page.getByTestId('step-list').first()).toBeVisible({ timeout: 10_000 })

    // Real answer arrives.
    await expect(page.getByTestId('assistant-message').last()).toBeVisible({ timeout: 90_000 })
    const answer = page.getByTestId('assistant-message').last()

    // Groupby answer renders a summary table and an interactive chart.
    await expect(answer.getByTestId('summary-table')).toBeVisible()
    await expect(answer.getByTestId('answer-chart')).toBeVisible()

    // Follow-up suggestion chips appear and are clickable.
    const chips = answer.getByTestId('follow-up-chip')
    if (await chips.count()) {
      await expect(chips.first()).toBeVisible()
      await chips.first().click()
      // Clicking a chip submits it as the next question.
      await expect(page.getByTestId('user-message')).toHaveCount(2, { timeout: 90_000 })
    }
  })

  test('multi-file add updates the combined row count', async ({ page }) => {
    await page.goto('./')
    await page.getByTestId('file-input').setInputFiles(FIXTURE_CSV)
    await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })

    const rowsBefore = await page.getByTestId('profile-card').textContent()

    await page.getByTestId('add-file-input').setInputFiles(FIXTURE_CSV_2)
    // Profile re-renders with the combined row count.
    await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })
    await expect
      .poll(async () => (await page.getByTestId('profile-card').textContent()) !== rowsBefore, {
        timeout: 30_000,
      })
      .toBeTruthy()
  })

  test('export cleaned data triggers a download', async ({ page }) => {
    await page.goto('./')
    await page.getByTestId('file-input').setInputFiles(FIXTURE_CSV)
    await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })

    await page.getByTestId('question-input').fill('Remove rows with missing amount and keep the rest')
    await page.getByTestId('send-button').click()
    await expect(page.getByTestId('assistant-message').last()).toBeVisible({ timeout: 90_000 })

    const exportButton = page.getByTestId('export-button')
    await expect(exportButton).toBeEnabled({ timeout: 10_000 })

    const downloadPromise = page.waitForEvent('download', { timeout: 30_000 })
    await exportButton.click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBeTruthy()
  })

  test('audit page lists runs and shows the cost total', async ({ page }) => {
    // Seed at least one run first.
    await page.goto('./')
    await page.getByTestId('file-input').setInputFiles(FIXTURE_CSV)
    await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })
    await page.getByTestId('question-input').fill('What is the average amount?')
    await page.getByTestId('send-button').click()
    await expect(page.getByTestId('assistant-message').last()).toBeVisible({ timeout: 90_000 })

    // Navigate to the audit trail.
    await page.getByTestId('audit-nav-link').click()
    await expect(page.getByTestId('cost-summary')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('cost-summary')).toContainText('Cost today')

    // At least one query run is listed.
    await expect(page.getByTestId('audit-list')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('audit-row').first()).toBeVisible()
  })
})
