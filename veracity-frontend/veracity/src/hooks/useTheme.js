/*
 * Light or dark. Follows the OS until the user picks one in the header; the
 * pick is remembered in localStorage and set as data-theme on <html>, which
 * tokens.css reads. index.html applies the saved pick before React loads so
 * the page never flashes the wrong theme.
 *
 * Switching crossfades the whole page (View Transitions, in Chrome and Brave);
 * other browsers ease the colours instead (.theme-switching in base.css).
 */
import { useEffect, useState } from 'react'
import { flushSync } from 'react-dom'

const KEY = 'veracity-theme'
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
const FADE_MS = 350

function readSaved() {
  try {
    const saved = localStorage.getItem(KEY)
    return saved === 'light' || saved === 'dark' ? saved : null
  } catch {
    return null // storage blocked (private window): just follow the OS
  }
}

export function useTheme() {
  const [saved, setSaved] = useState(readSaved)
  const [systemDark, setSystemDark] = useState(darkQuery.matches)

  useEffect(() => {
    const onChange = (event) => setSystemDark(event.matches)
    darkQuery.addEventListener('change', onChange)
    return () => darkQuery.removeEventListener('change', onChange)
  }, [])

  const theme = saved ?? (systemDark ? 'dark' : 'light')

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark'
    const root = document.documentElement

    function apply() {
      setSaved(next)
      root.dataset.theme = next
      try {
        localStorage.setItem(KEY, next)
      } catch {
        // not remembered, still applied for this visit
      }
    }

    if (reducedMotion.matches) {
      apply()
    } else if (document.startViewTransition) {
      // flushSync so React paints the new icon inside the transition snapshot
      document.startViewTransition(() => flushSync(apply))
    } else {
      root.classList.add('theme-switching')
      apply()
      setTimeout(() => root.classList.remove('theme-switching'), FADE_MS)
    }
  }

  return { theme, toggle }
}
