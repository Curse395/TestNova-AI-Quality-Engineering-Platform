export const navItems = [
  { label: 'Overview', icon: 'LayoutGrid', href: '/' },
  { label: 'Projects', icon: 'FolderKanban', href: '/projects' },
  { label: 'Upload Center', icon: 'Upload', href: '/upload' },
  { label: 'Quality Analytics', icon: 'BarChart3', href: '/analytics' },
  { label: 'AI Assistant', icon: 'Bot', href: '/assistant' },
]

export const performanceData = [
  { name: 'Jan', coverage: 78, speed: 64 },
  { name: 'Feb', coverage: 82, speed: 71 },
  { name: 'Mar', coverage: 84, speed: 76 },
  { name: 'Apr', coverage: 88, speed: 79 },
  { name: 'May', coverage: 91, speed: 83 },
  { name: 'Jun', coverage: 95, speed: 88 },
]

export const projects = [
  { name: 'Atlas Commerce', status: 'Healthy', owner: 'Mina', progress: '92%' },
  { name: 'Northstar API', status: 'Needs review', owner: 'Jules', progress: '74%' },
  { name: 'Pulse CRM', status: 'Stable', owner: 'Drew', progress: '88%' },
]

export const uploads = [
  { name: 'release-4.3.apk', type: 'Mobile bundle', size: '184 MB', time: '5m ago' },
  { name: 'checkout-flow.json', type: 'Scenario pack', size: '12 MB', time: '14m ago' },
  { name: 'auth-suite.csv', type: 'Regression data', size: '7 MB', time: '21m ago' },
]

export const messages = [
  { from: 'assistant', text: 'I highlighted two flaky tests and suggested a safer retry policy.' },
  { from: 'user', text: 'Can you summarize the newest regression risk for the billing flow?' },
  { from: 'assistant', text: 'Billing flow risk is down 18% after the last patch and the highest-likelihood issue is token refresh timing.' },
]
