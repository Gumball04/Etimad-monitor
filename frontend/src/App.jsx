import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api/client'

const emptyForm = { keyword: '', max_pages: 5, page_size: 6 }
const intervalOptions = [1, 2, 4, 6, 8, 12, 24]

function formatDateTime(value, timezone) {
  if (!value) return 'لا يوجد بعد'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ar-JO', {
    dateStyle: 'medium',
    timeStyle: 'short',
    hour12: true,
    timeZone: timezone || undefined,
  }).format(date)
}

function formatDailyTime(hour, minute) {
  const safeHour = Number(hour || 0)
  const safeMinute = Number(minute || 0)
  const date = new Date()
  date.setHours(safeHour, safeMinute, 0, 0)
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date)
}

function getErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

function FieldLabel({ children }) {
  return <div className="mb-2 text-sm font-semibold text-slate-700">{children}</div>
}

function KeywordChip({ keyword, deleting, onDelete }) {
  return (
    <div className="inline-flex items-center gap-3 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-sm">
      <button
        type="button"
        onClick={onDelete}
        disabled={deleting}
        className="font-semibold text-rose-600 transition hover:text-rose-700 disabled:opacity-50"
      >
        {deleting ? 'جارٍ الحذف...' : 'حذف'}
      </button>
      <span>{keyword.keyword}</span>
    </div>
  )
}

function TenderCard({ tender }) {
  return (
    <div className="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="flex-1 text-right">
          <h3 className="text-lg font-bold leading-8 text-slate-900 md:text-xl">
            {tender.tender_title || 'بدون اسم'}
          </h3>

          <div className="mt-4 grid grid-cols-1 gap-2 text-sm text-slate-600 md:grid-cols-2">
            <div><span className="font-semibold text-slate-800">رقم المنافسة:</span> {tender.tender_number || '-'}</div>
            <div><span className="font-semibold text-slate-800">الجهة الحكومية:</span> {tender.government_entity || '-'}</div>
            <div><span className="font-semibold text-slate-800">الحالة:</span> {tender.status || '-'}</div>
            <div><span className="font-semibold text-slate-800">الوقت المتبقي:</span> {tender.remaining_time || '-'}</div>
          </div>
        </div>

        {tender.tender_url ? (
          <a
            href={tender.tender_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center justify-center rounded-2xl bg-slate-900 px-4 py-3 text-sm font-medium text-white hover:bg-slate-800"
          >
            فتح المنافسة
          </a>
        ) : null}
      </div>

      <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm leading-7 text-slate-700">
        <span className="font-semibold text-slate-800">الغرض من المنافسة:</span>{' '}
        {tender.purpose || '-'}
      </div>
    </div>
  )
}

export default function App() {
  const [form, setForm] = useState(emptyForm)
  const [keywords, setKeywords] = useState([])
  const [keywordValue, setKeywordValue] = useState('')
  const [keywordsLoading, setKeywordsLoading] = useState(true)
  const [keywordsSubmitting, setKeywordsSubmitting] = useState(false)
  const [keywordsError, setKeywordsError] = useState('')
  const [keywordsSuccess, setKeywordsSuccess] = useState('')
  const [deletingKeywordIds, setDeletingKeywordIds] = useState([])
  const [automation, setAutomation] = useState({
    enabled: false,
    schedule_mode: 'interval',
    interval_hours: 1,
    daily_hour: 9,
    daily_minute: 0,
    last_run_at: null,
    last_status: null,
    last_error: null,
    timezone: 'Asia/Amman',
    email_ready: false,
    email_recipient: null,
  })
  const [loading, setLoading] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [savingAutomation, setSavingAutomation] = useState(false)
  const [runningAutomation, setRunningAutomation] = useState(false)
  const [syncingLatest, setSyncingLatest] = useState(false)
  const [tenders, setTenders] = useState([])
  const [scrapeSummary, setScrapeSummary] = useState(null)
  const lastRunRef = useRef(null)

  const hasSavedKeywords = keywords.length > 0
  const currentRunReferenceNumbers = useMemo(
    () => [...new Set((tenders || []).map((item) => item.reference_number).filter(Boolean))],
    [tenders]
  )

  const loadLatestTenders = async (silent = false) => {
    if (!silent) setSyncingLatest(true)
    try {
      const response = await api.get('/tenders', { params: { limit: 100 } })
      setTenders(response.data || [])
    } catch (error) {
      console.error(error)
    } finally {
      if (!silent) setSyncingLatest(false)
    }
  }

  const loadKeywords = async () => {
    setKeywordsLoading(true)
    try {
      const response = await api.get('/keywords')
      setKeywords(response.data || [])
    } catch (error) {
      console.error(error)
      setKeywordsError(getErrorMessage(error, 'تعذر تحميل الكلمات المفتاحية'))
    } finally {
      setKeywordsLoading(false)
    }
  }

  const loadAutomation = async (options = {}) => {
    const { refreshTendersOnChange = false } = options
    try {
      const response = await api.get('/automation')
      const data = response.data || {}
      const nextLastRun = data.last_run_at || null
      const hasNewRun = refreshTendersOnChange && nextLastRun && nextLastRun !== lastRunRef.current

      setAutomation({
        enabled: Boolean(data.enabled),
        schedule_mode: data.schedule_mode || 'interval',
        interval_hours: Number(data.interval_hours || 1),
        daily_hour: Number(data.daily_hour ?? 9),
        daily_minute: Number(data.daily_minute ?? 0),
        last_run_at: nextLastRun,
        last_status: data.last_status || null,
        last_error: data.last_error || null,
        timezone: data.timezone || 'Asia/Amman',
        email_ready: Boolean(data.email_ready),
        email_recipient: data.email_recipient || null,
      })
      setForm((current) => ({
        keyword: data.keyword || current.keyword,
        max_pages: Number(data.max_pages || current.max_pages || 5),
        page_size: Number(data.page_size || current.page_size || 6),
      }))

      if (hasNewRun) {
        await loadLatestTenders(true)
      }
      lastRunRef.current = nextLastRun
    } catch (error) {
      console.error(error)
    }
  }

  useEffect(() => {
    const bootstrap = async () => {
      await Promise.all([loadKeywords(), loadAutomation()])
      await loadLatestTenders()
    }
    bootstrap()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadAutomation({ refreshTendersOnChange: true })
    }, 15000)
    return () => window.clearInterval(timer)
  }, [])

  const handleScrape = async (e) => {
    e.preventDefault()

    if (!hasSavedKeywords && !form.keyword.trim()) {
      alert('اكتب كلمة مفتاحية أولاً')
      return
    }

    setLoading(true)
    setTenders([])
    setScrapeSummary(null)

    try {
      const response = await api.post('/scrape', {
        keyword: form.keyword,
        max_pages: Number(form.max_pages),
        page_size: Number(form.page_size),
      })
      setTenders(response.data.items || [])
      setScrapeSummary(response.data)
      await loadAutomation()
    } catch (error) {
      console.error(error)
      alert(getErrorMessage(error, 'حدث خطأ أثناء السحب'))
    } finally {
      setLoading(false)
    }
  }

  const handleAddKeyword = async (e) => {
    e.preventDefault()
    if (!keywordValue.trim()) {
      setKeywordsSuccess('')
      setKeywordsError('اكتب كلمة مفتاحية صحيحة أولاً')
      return
    }

    setKeywordsSubmitting(true)
    setKeywordsError('')
    setKeywordsSuccess('')
    try {
      const response = await api.post('/keywords', { keyword: keywordValue })
      setKeywords((current) => [response.data, ...current])
      setKeywordValue('')
      setKeywordsSuccess('تمت إضافة الكلمة المفتاحية')
    } catch (error) {
      console.error(error)
      setKeywordsError(getErrorMessage(error, 'تعذر إضافة الكلمة المفتاحية'))
    } finally {
      setKeywordsSubmitting(false)
    }
  }

  const handleDeleteKeyword = async (keywordId) => {
    setDeletingKeywordIds((current) => [...current, keywordId])
    setKeywordsError('')
    setKeywordsSuccess('')
    try {
      await api.delete(`/keywords/${keywordId}`)
      setKeywords((current) => current.filter((keyword) => keyword.id !== keywordId))
    } catch (error) {
      console.error(error)
      setKeywordsError(getErrorMessage(error, 'تعذر حذف الكلمة المفتاحية'))
    } finally {
      setDeletingKeywordIds((current) => current.filter((id) => id !== keywordId))
    }
  }

  const saveAutomation = async () => {
    if (!hasSavedKeywords && !form.keyword.trim()) {
      alert('لازم يكون في keyword محفوظ للأتمتة أو كلمة يدوية عند عدم وجود كلمات محفوظة')
      return
    }

    setSavingAutomation(true)
    try {
      const response = await api.put('/automation', {
        enabled: automation.enabled,
        schedule_mode: automation.schedule_mode,
        interval_hours: Number(automation.interval_hours),
        daily_hour: automation.schedule_mode === 'daily_time' ? Number(automation.daily_hour) : null,
        daily_minute: automation.schedule_mode === 'daily_time' ? Number(automation.daily_minute) : null,
        keyword: form.keyword,
        max_pages: Number(form.max_pages),
        page_size: Number(form.page_size),
      })
      const data = response.data || {}
      setAutomation((current) => ({
        ...current,
        enabled: Boolean(data.enabled),
        schedule_mode: data.schedule_mode || 'interval',
        interval_hours: Number(data.interval_hours || 1),
        daily_hour: Number(data.daily_hour ?? current.daily_hour ?? 9),
        daily_minute: Number(data.daily_minute ?? current.daily_minute ?? 0),
        last_run_at: data.last_run_at || null,
        last_status: data.last_status || null,
        last_error: data.last_error || null,
        timezone: data.timezone || current.timezone || 'Asia/Amman',
        email_ready: Boolean(data.email_ready),
        email_recipient: data.email_recipient || null,
      }))
      lastRunRef.current = data.last_run_at || lastRunRef.current
      alert('تم حفظ إعدادات الأتمتة')
    } catch (error) {
      console.error(error)
      alert(getErrorMessage(error, 'فشل حفظ إعدادات الأتمتة'))
    } finally {
      setSavingAutomation(false)
    }
  }

  const runAutomationNow = async () => {
    setRunningAutomation(true)
    try {
      const response = await api.post('/automation/run-now')
      setTenders(response.data.items || [])
      setScrapeSummary(response.data)
      await loadAutomation()
      alert('تم تشغيل السحب الآن')
    } catch (error) {
      console.error(error)
      alert(getErrorMessage(error, 'فشل التشغيل الفوري'))
    } finally {
      setRunningAutomation(false)
    }
  }

  const downloadExcel = () => {
    const baseUrl = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'}/tenders/export`
    const params = new URLSearchParams()
    currentRunReferenceNumbers.forEach((referenceNumber) => params.append('reference_numbers', referenceNumber))
    const exportUrl = params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl
    window.open(exportUrl, '_blank')
  }

  const resetDatabase = async () => {
    const confirmed = window.confirm('متأكد من حذف الـ Database؟')
    if (!confirmed) return
    setResetting(true)
    try {
      await api.delete('/tenders/reset-db')
      setTenders([])
      setScrapeSummary(null)
      alert('تم تصفير قاعدة البيانات')
    } catch (error) {
      console.error(error)
      alert('حدث خطأ أثناء تصفير قاعدة البيانات')
    } finally {
      setResetting(false)
    }
  }

  const runModeMessage = keywordsLoading
    ? 'جارٍ التحقق من الكلمات المفتاحية المحفوظة قبل التنفيذ.'
    : hasSavedKeywords
      ? `سيتم تشغيل السحب مرة لكل كلمة محفوظة (${keywords.length}) ثم تجهيز ملف Excel مستقل لكل كلمة وإرسالهم كلهم بإيميل واحد فقط.`
      : 'لا توجد كلمات محفوظة حالياً، لذلك سيعمل التنفيذ على الكلمة اليدوية الموجودة في الحقل.'

  return (
    <div className="min-h-screen bg-slate-100" dir="rtl">
      <div className="mx-auto max-w-6xl p-4 md:p-6">
        <div className="rounded-[2rem] bg-slate-950 px-6 py-8 text-center text-white shadow-lg">
          <h1 className="text-3xl font-bold md:text-4xl">سحب منافسات اعتماد</h1>
          <p className="mt-2 text-sm text-slate-300 md:text-base">دمج الأتمتة + الإيميل + الكلمات المتعددة بدون المساس بمنطق السحب</p>
        </div>

        <div className="mt-6 rounded-[2rem] bg-white p-6 shadow-sm">
          <div className="mb-5 flex flex-col gap-3 text-right md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-2xl font-bold text-slate-900">الكلمات المفتاحية</h2>
              <p className="mt-1 text-sm text-slate-500">كل كلمة محفوظة ستنفذ كسحب مستقل ويُنتج لها ملف Excel خاص، ثم تُرسل جميع الملفات بإيميل واحد فقط.</p>
            </div>
            <span className="w-fit rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{keywords.length} كلمة</span>
          </div>

          <form onSubmit={handleAddKeyword} className="space-y-3">
            <div className="flex flex-col gap-3 md:flex-row">
              <button type="submit" disabled={keywordsSubmitting} className="shrink-0 rounded-2xl bg-emerald-600 px-5 py-3 text-white transition hover:bg-emerald-700 disabled:opacity-50">
                {keywordsSubmitting ? 'جارٍ الإضافة...' : 'إضافة كلمة مفتاحية'}
              </button>
              <input
                className="flex-1 rounded-2xl border border-slate-300 px-4 py-3 text-right outline-none focus:border-slate-500"
                placeholder="مثال: غاز، اتصالات، أجهزة تقنية"
                value={keywordValue}
                onChange={(e) => setKeywordValue(e.target.value)}
              />
            </div>

            {keywordsError ? <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-right text-sm text-rose-700">{keywordsError}</div> : null}
            {!keywordsError && keywordsSuccess ? <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-right text-sm text-emerald-700">{keywordsSuccess}</div> : null}
          </form>

          <div className="mt-4 rounded-3xl border border-dashed border-slate-300 bg-slate-50 p-4">
            {keywordsLoading ? (
              <div className="text-center text-sm text-slate-500">جارٍ تحميل الكلمات المفتاحية...</div>
            ) : keywords.length === 0 ? (
              <div className="text-center text-sm text-slate-500">لا توجد كلمات محفوظة حتى الآن.</div>
            ) : (
              <div className="flex flex-wrap justify-end gap-3">
                {keywords.map((keyword) => (
                  <KeywordChip
                    key={keyword.id}
                    keyword={keyword}
                    deleting={deletingKeywordIds.includes(keyword.id)}
                    onDelete={() => handleDeleteKeyword(keyword.id)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="mt-6 rounded-[2rem] bg-white p-6 shadow-sm">
          <div className="mb-5 flex flex-col gap-2 text-right md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-2xl font-bold text-slate-900">تشغيل السحب</h2>
              <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">{runModeMessage}</div>
            </div>
            <div className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">آخر النتائج محفوظة في قاعدة البيانات ويمكن تحميلها Excel</div>
          </div>

          <form onSubmit={handleScrape} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <div className="md:col-span-2">
                <FieldLabel>الكلمة اليدوية الاحتياطية</FieldLabel>
                <input
                  className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-right outline-none focus:border-slate-500"
                  placeholder="تُستخدم فقط إذا لم توجد كلمات محفوظة"
                  value={form.keyword}
                  onChange={(e) => setForm({ ...form, keyword: e.target.value })}
                />
              </div>

              <div>
                <FieldLabel>عدد الصفحات</FieldLabel>
                <input type="number" className="w-full rounded-2xl border border-slate-300 px-4 py-3 outline-none focus:border-slate-500" value={form.max_pages} onChange={(e) => setForm({ ...form, max_pages: e.target.value })} />
              </div>

              <div>
                <FieldLabel>عدد العناصر بالصفحة</FieldLabel>
                <input type="number" className="w-full rounded-2xl border border-slate-300 px-4 py-3 outline-none focus:border-slate-500" value={form.page_size} onChange={(e) => setForm({ ...form, page_size: e.target.value })} />
              </div>
            </div>

            <div className="flex flex-wrap justify-end gap-3">
              <button type="button" onClick={resetDatabase} disabled={resetting} className="rounded-2xl bg-rose-600 px-5 py-3 text-white transition hover:bg-rose-700 disabled:opacity-50">
                {resetting ? 'جارٍ التصفير...' : 'حذف الداتا'}
              </button>
              <button type="button" onClick={downloadExcel} className="rounded-2xl bg-emerald-600 px-5 py-3 text-white transition hover:bg-emerald-700">تحميل Excel</button>
              <button type="submit" disabled={loading} className="rounded-2xl bg-slate-900 px-5 py-3 text-white disabled:opacity-50">
                {loading ? (hasSavedKeywords ? 'جارٍ تشغيل الكلمات المحفوظة...' : 'جارٍ البحث...') : 'بحث وسحب المنافسات'}
              </button>
            </div>
          </form>

          {scrapeSummary ? (
            <div className="mt-4 rounded-[1.5rem] border border-slate-200 bg-slate-50 p-4 text-right text-sm text-slate-700">
              <div className="grid gap-3 md:grid-cols-4">
                <div><span className="font-semibold text-slate-900">وضع التنفيذ:</span> {scrapeSummary.execution_mode || 'manual'}</div>
                <div><span className="font-semibold text-slate-900">النتائج:</span> {scrapeSummary.total_found || 0}</div>
                <div><span className="font-semibold text-slate-900">المحفوظ:</span> {scrapeSummary.total_saved || 0}</div>
                <div><span className="font-semibold text-slate-900">الجديد:</span> {scrapeSummary.new_items_count || 0}</div>
              </div>
              {Array.isArray(scrapeSummary.executed_keywords) && scrapeSummary.executed_keywords.length > 0 ? (
                <div className="mt-3"><span className="font-semibold text-slate-900">الكلمات المنفذة:</span> {scrapeSummary.executed_keywords.join('، ')}</div>
              ) : null}
              {scrapeSummary.auto_email_message ? <div className="mt-2 text-slate-500">{scrapeSummary.auto_email_message}</div> : null}
            </div>
          ) : null}
        </div>

        <div className="mt-6 rounded-[2rem] bg-white p-6 shadow-sm">
          <div className="mb-5 flex flex-col gap-2 text-right md:flex-row md:items-center md:justify-between">
            <h2 className="text-2xl font-bold text-slate-900">الأتمتة</h2>
            <div className="rounded-2xl bg-slate-50 px-4 py-2 text-sm text-slate-600">التوقيت المستخدم: <span className="font-semibold text-slate-800">{automation.timezone || 'Asia/Amman'}</span></div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 p-4">
              <FieldLabel>الحالة الحالية</FieldLabel>
              <div className="space-y-2 text-sm leading-7 text-slate-700">
                <div><span className="font-semibold text-slate-800">آخر تشغيل:</span> {formatDateTime(automation.last_run_at, automation.timezone)}</div>
                <div><span className="font-semibold text-slate-800">الحالة:</span> {automation.last_status || 'لا يوجد بعد'}</div>
                {automation.last_error ? <div className="text-rose-700"><span className="font-semibold">آخر خطأ:</span> {automation.last_error}</div> : null}
              </div>
            </div>

            <div className="rounded-[1.5rem] border border-slate-200 bg-white p-4">
              <FieldLabel>وضع التشغيل</FieldLabel>
              <select className="w-full rounded-2xl border border-slate-300 px-4 py-3 outline-none focus:border-slate-500" value={automation.schedule_mode} onChange={(e) => setAutomation({ ...automation, schedule_mode: e.target.value })}>
                <option value="interval">كل عدة ساعات</option>
                <option value="daily_time">يومياً بوقت محدد</option>
              </select>
              <label className="mt-4 flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-700">تفعيل الأتمتة</span>
                <input type="checkbox" checked={automation.enabled} onChange={(e) => setAutomation({ ...automation, enabled: e.target.checked })} />
              </label>
            </div>

            <div className="rounded-[1.5rem] border border-slate-200 bg-white p-4 lg:col-span-2">
              {automation.schedule_mode === 'interval' ? (
                <>
                  <FieldLabel>فاصل التشغيل</FieldLabel>
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px] md:items-center">
                    <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">سيُعاد التشغيل تلقائياً حسب الفاصل المحدد مع الحفاظ على نفس منطق الأتمتة الحالي.</div>
                    <select className="w-full rounded-2xl border border-slate-300 px-4 py-3 outline-none focus:border-slate-500" value={automation.interval_hours} onChange={(e) => setAutomation({ ...automation, interval_hours: Number(e.target.value) })}>
                      {intervalOptions.map((hours) => <option key={hours} value={hours}>كل {hours} ساعة</option>)}
                    </select>
                  </div>
                </>
              ) : (
                <>
                  <FieldLabel>الوقت اليومي</FieldLabel>
                  <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_260px]">
                    <div className="rounded-[1.5rem] border border-slate-200 bg-gradient-to-br from-slate-900 to-slate-700 p-5 text-white shadow-sm">
                      <div className="text-sm text-slate-300">التنفيذ اليومي</div>
                      <div className="mt-2 text-3xl font-bold tracking-wide">{formatDailyTime(automation.daily_hour, automation.daily_minute)}</div>
                      <div className="mt-3 text-sm text-slate-300">سيظهر هذا الوقت كموعد التشغيل اليومي في البطاقة بشكل أوضح ومرتب.</div>
                    </div>
                    <div className="rounded-[1.5rem] border border-slate-200 bg-slate-50 p-4">
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <FieldLabel>الساعة</FieldLabel>
                          <input type="number" min="0" max="23" className="w-full rounded-2xl border border-slate-300 px-3 py-3 outline-none focus:border-slate-500" value={automation.daily_hour} onChange={(e) => setAutomation({ ...automation, daily_hour: e.target.value })} />
                        </div>
                        <div>
                          <FieldLabel>الدقيقة</FieldLabel>
                          <input type="number" min="0" max="59" className="w-full rounded-2xl border border-slate-300 px-3 py-3 outline-none focus:border-slate-500" value={automation.daily_minute} onChange={(e) => setAutomation({ ...automation, daily_minute: e.target.value })} />
                        </div>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap justify-end gap-3">
            <button type="button" onClick={runAutomationNow} disabled={runningAutomation} className="rounded-2xl bg-amber-500 px-5 py-3 text-white transition hover:bg-amber-600 disabled:opacity-50">
              {runningAutomation ? 'جارٍ التشغيل...' : 'تشغيل الآن'}
            </button>
            <button type="button" onClick={saveAutomation} disabled={savingAutomation} className="rounded-2xl bg-slate-900 px-5 py-3 text-white disabled:opacity-50">
              {savingAutomation ? 'جارٍ الحفظ...' : 'حفظ الأتمتة'}
            </button>
          </div>
        </div>

        <div className="mx-auto mt-6 max-w-5xl rounded-[2rem] bg-white p-6 shadow-sm">
          <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <h2 className="text-2xl font-bold text-slate-900">النتائج</h2>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">{tenders.length} نتيجة</span>
              <button type="button" onClick={() => loadLatestTenders()} disabled={syncingLatest} className="rounded-full border border-slate-200 px-3 py-1 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
                {syncingLatest ? 'جارٍ التحديث...' : 'تحديث النتائج من الداتابيس'}
              </button>
            </div>
          </div>

          <div className="space-y-4">
            {tenders.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-slate-500">لا توجد نتائج الآن. ابدأ بعملية بحث أو انتظر الأتمتة ثم حدّث النتائج.</div>
            ) : (
              tenders.map((tender, index) => <TenderCard key={tender.reference_number || tender.tender_url || index} tender={tender} />)
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
