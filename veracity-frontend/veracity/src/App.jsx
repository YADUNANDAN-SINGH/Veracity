import React, {useEffect, useState} from 'react'

// use assets folder to store images, fonts, and other static assets [./assets/]
import './App.css'

const API_URL = 'http://localhost:8000'

const useBackendMessage = () => {
  const [message, setMessage] = useState('')
  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(`${API_URL}/`);
        const data = await response.json();
        setMessage(data.message);
      } catch (error) {
        console.error('Error fetching data:', error);
      }
    };

    fetchData();
  }, []);

  return message;
}

function App() {
  const [count, setCount] = useState(0)
  const message = useBackendMessage()

  return (
    <>
    Welcome to Veracity Frontend! <br />
    Here is the message from the backend: {message} <br />
    </>
  )
}

export default App
