import { test, expect } from '@playwright/test'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * Reads AGENT_SMTP_FROM_ADDRESS from the repo-root `.env` file, following the
 * same "address the test send to the service account's own mailbox" real-SMTP
 * convention used by the backend's tests/phase1/test_smtp_real_send.py.
 *
 * We do not want to spam a third party during this E2E run, so — same as the
 * backend gate — the recipient is the SMTP service account's own address.
 */
function readSmtpFromAddress(): string | null {
  const envPath = resolve(__dirname, '..', '..', '..', '.env')
  if (!existsSync(envPath)) return null

  const contents = readFileSync(envPath, 'utf-8')
  for (const line of contents.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const [key, ...rest] = trimmed.split('=')
    if (key.trim() === 'AGENT_SMTP_FROM_ADDRESS') {
      const value = rest.join('=').trim()
      return value.length > 0 ? value : null
    }
  }
  return null
}

const fixturePath = resolve(__dirname, '..', 'fixtures', 'gr_export_small.csv')
const recipient = readSmtpFromAddress()

test.describe('GR Report Agent — primary journey', () => {
  test.skip(
    !recipient,
    'AGENT_SMTP_FROM_ADDRESS is not set in .env — real SMTP send cannot be exercised.'
  )

  test('upload a GR export, enter a recipient, and send the report', async ({ page }) => {
    await page.goto('/app/')

    // Idle state: helper copy is visible, never a blank panel.
    await expect(
      page.getByText(/Upload your GR export \(CSV or QVD\)/i)
    ).toBeVisible()

    const sendButton = page.getByRole('button', { name: 'Send Report' })
    await expect(sendButton).toBeDisabled()

    // Choose the fixture file via the hidden file input.
    await page.locator('input[type="file"]').setInputFiles(fixturePath)
    await expect(page.getByText('gr_export_small.csv')).toBeVisible()

    // Still disabled until recipients has at least one non-empty line.
    await expect(sendButton).toBeDisabled()

    await page.getByLabel('Recipients').fill(recipient as string)
    await expect(sendButton).toBeEnabled()

    await sendButton.click()

    // Loading state: button disables and reads the exact loading copy.
    await expect(sendButton).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Generating & sending report…' })).toBeVisible()

    // Success state: real send, real response — not a spinner, not an error.
    await expect(page.getByText(/Report sent to \d+ recipient/)).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Source file: gr_export_small.csv')).toBeVisible()
    await expect(page.getByText(/Reporting period:/)).toBeVisible()
  })
})
