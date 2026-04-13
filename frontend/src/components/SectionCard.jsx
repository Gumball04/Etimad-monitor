export default function SectionCard({ title, children, actions }) {
  return (
    <section className="rounded-2xl bg-white p-5 shadow-sm border border-slate-200">
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="text-lg font-bold text-slate-800">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  )
}
