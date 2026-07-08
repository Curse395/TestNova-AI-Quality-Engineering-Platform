import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { uploads } from '../data/mockData'

const UploadPage = () => {
  return (
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Upload Center" subtitle="Artifacts" />
        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <Card title="Drop assets" subtitle="Upload test bundles, scenarios, and release artifacts.">
            <div className="rounded-3xl border border-dashed border-slate-700 bg-slate-950/70 p-10 text-center">
              <p className="text-lg font-semibold text-white">Drag and drop your files here</p>
              <p className="mt-2 text-sm text-slate-400">APK, CSV, JSON, XML, and build logs supported.</p>
              <Button className="mt-6">Browse files</Button>
            </div>
          </Card>

          <Card title="Recent uploads" subtitle="Latest items processed by the AI pipeline">
            <div className="space-y-3">
              {uploads.map((item) => (
                <div key={item.name} className="flex items-center justify-between rounded-2xl bg-slate-950/70 px-3 py-3">
                  <div>
                    <p className="font-medium text-white">{item.name}</p>
                    <p className="text-sm text-slate-400">{item.type}</p>
                  </div>
                  <div className="text-right text-sm text-slate-400">
                    <p>{item.size}</p>
                    <p>{item.time}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default UploadPage
