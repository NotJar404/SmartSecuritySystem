namespace WebApp.Models
{
    public class Occupancy
    {
        public int Id { get; set; }

        public string RoomName { get; set; }
        public int CurrentCount { get; set; }
        public int MaxCapacity { get; set; }
    }
}