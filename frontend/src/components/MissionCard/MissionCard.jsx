/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from 'react';
import './MissionCard.css';
export default memo(function MissionCard({
  children,
  ...props
}) {
  return <article {...props}>{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }{children}</article>;
});
